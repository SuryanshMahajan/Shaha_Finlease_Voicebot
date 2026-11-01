import logging

from fastapi.testclient import TestClient

from app.core.security import audit_event, limiter
from app.core.config import get_settings
from app.main import app
from tests.security_helpers import admin_headers


def test_admin_routes_fail_closed_without_authentication():
    client = TestClient(app)
    paths = [
        ("GET", "/api/customers"), ("POST", "/api/customers/import"),
        ("GET", "/api/calls"), ("POST", "/api/calls"),
        ("GET", "/api/analytics/overview"),
    ]
    for method, path in paths:
        response = client.request(method, path)
        assert response.status_code == 401, (method, path, response.status_code)


def test_customer_and_call_detail_actions_require_authentication():
    client = TestClient(app)
    record_id = "00000000-0000-0000-0000-000000000001"
    requests = [
        ("GET", f"/api/customers/{record_id}", None),
        ("POST", f"/api/customers/{record_id}/verify", {"display_name": "Synthetic", "birth_year": "1980"}),
        ("GET", f"/api/calls/{record_id}", None),
        ("PATCH", f"/api/calls/{record_id}/outcome", {"outcome": "right_customer"}),
    ]
    for method, path, payload in requests:
        response = client.request(method, path, json=payload)
        assert response.status_code == 401, (method, path, response.status_code)


def test_login_rejects_invalid_credentials_generically():
    client = TestClient(app)
    response = client.post("/api/auth/login", data={"username": "unknown", "password": "wrong"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password."


def test_login_fails_closed_when_authentication_is_unconfigured():
    from app.core.config import Settings

    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="postgresql+psycopg://test:test@localhost/test",
        admin_username="", admin_password_hash="", jwt_secret="",
    )
    try:
        response = TestClient(app).post("/api/auth/login", data={"username": "any", "password": "any"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503


def test_login_issues_bearer_token_for_valid_credentials():
    response = TestClient(app).post("/api/auth/login", data={"username": "test-admin", "password": "test-only-password"})
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_non_admin_role_is_denied():
    response = TestClient(app, headers=admin_headers(role="viewer")).get("/api/analytics/overview")
    assert response.status_code == 403


def test_login_rate_limit_returns_429():
    limiter.reset()
    client = TestClient(app)
    responses = [client.post("/api/auth/login", data={"username": "x", "password": "x"}) for _ in range(6)]
    assert responses[-1].status_code == 429
    assert responses[-1].headers.get("retry-after")


def test_audit_event_is_structured_without_sensitive_values(caplog):
    caplog.set_level(logging.INFO, logger="shaha.security")
    audit_event("identity_verification", "failure")
    record = caplog.records[-1].getMessage()
    assert '"event":"identity_verification"' in record
    assert '"outcome":"failure"' in record
    assert "birth_year" not in record
    assert "access_token" not in record
    assert "test-only-password" not in record


def test_login_audit_record_excludes_credentials(caplog):
    caplog.set_level(logging.INFO, logger="shaha.security")
    TestClient(app).post("/api/auth/login", data={"username": "test-admin", "password": "test-only-password"})
    record = caplog.records[-1].getMessage()
    assert '"event":"authentication"' in record
    assert "test-admin" not in record
    assert "test-only-password" not in record
    assert "access_token" not in record
