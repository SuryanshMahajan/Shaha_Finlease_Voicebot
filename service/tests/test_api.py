import os
import uuid
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_db
from app.main import app
from app.models import Call, CallStatus, Customer, DoNotCallEvent
from tests.security_helpers import admin_headers

client = TestClient(app, headers=admin_headers())


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_fails_when_database_is_down():
    class BrokenSession:
        def execute(self, *_args, **_kwargs):
            raise OperationalError("SELECT 1", {}, RuntimeError("unavailable"))

        def close(self):
            pass

    app.dependency_overrides[get_db] = lambda: BrokenSession()
    try:
        response = client.get("/api/health/ready")
        assert response.status_code == 503
        assert response.json()["detail"] == "Database unavailable"
    finally:
        app.dependency_overrides.clear()


def test_call_pagination_validation():
    assert client.get("/api/calls?limit=1000").status_code == 422


def test_call_request_validation():
    response = client.post("/api/calls", json={"direction": "sideways"})
    assert response.status_code == 422
    outbound_without_customer = client.post("/api/calls", json={"direction": "outbound"})
    assert outbound_without_customer.status_code == 422


def test_protected_calls_reject_missing_and_invalid_credentials():
    assert TestClient(app).get("/api/calls").status_code == 401
    assert TestClient(app, headers={"Authorization": "Bearer invalid"}).get("/api/calls").status_code == 401
    assert TestClient(app).get("/api/providers/status").status_code == 401
    assert TestClient(app).get(f"/api/calls/{uuid.uuid4()}/events").status_code == 401


def test_provider_readiness_is_secret_free_and_does_not_claim_live_calls():
    response = client.get("/api/providers/status")
    assert response.status_code == 200
    body = response.json()
    assert {provider["name"] for provider in body["providers"]} == {"stt", "llm", "tts", "telephony", "analysis", "local_mocks", "gemini", "twilio_conversation_relay"}
    assert all(provider["configured"] is False and provider["mode"] == ("optional" if provider["name"] == "gemini" else "unconfigured") for provider in body["providers"] if provider["name"] not in {"local_mocks", "twilio_conversation_relay"})
    assert next(provider for provider in body["providers"] if provider["name"] == "local_mocks")["state"] == "simulated"
    assert next(provider for provider in body["providers"] if provider["name"] == "twilio_conversation_relay")["state"] == "unconfigured"
    assert body["real_calls_enabled"] is False
    assert "secret" not in response.text.lower()


def test_call_status_transition_is_persisted_and_terminal():
    call_id = uuid.uuid4()
    call = Call(id=call_id, direction="inbound", status=CallStatus.queued, callback_requested=False, simulated=True,
                started_at=datetime.now(timezone.utc), transcript=[], callbacks=[], customer=None, summary_record=None)

    class Session:
        events = []
        def get(self, model, key):
            return call if model is Call and key == call_id else None
        def add(self, event): self.events.append(event)
        def commit(self): pass
        def refresh(self, _row): pass

    session = Session()
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = client.patch(f"/api/calls/{call_id}/status", json={"status": "completed"})
        repeated = client.patch(f"/api/calls/{call_id}/status", json={"status": "failed"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["simulated"] is True
    assert call.ended_at is not None
    assert len(session.events) == 1 and session.events[0].event_type == "status_changed"
    assert repeated.status_code == 409


def test_dnc_cannot_be_cleared_by_edit_and_release_is_audited():
    customer_id = uuid.uuid4()
    customer = Customer(id=customer_id, customer_ref="DEMO-DNC", display_name="Demo", birth_year=1980, preferred_language="en",
                        do_not_call=True, verification_status="unverified", created_at=datetime.now(timezone.utc))
    class Session:
        added = []
        def get(self, model, key): return customer if model is Customer and key == customer_id else None
        def add(self, row): self.added.append(row)
        def commit(self): pass
        def refresh(self, _row): pass
    session = Session()
    app.dependency_overrides[get_db] = lambda: session
    try:
        edit = client.patch(f"/api/customers/{customer_id}", json={"customer_ref": "DEMO-DNC", "display_name": "Demo", "birth_year": 1980, "do_not_call": False})
        release = client.post(f"/api/customers/{customer_id}/do-not-call/release", json={"reason": "Customer requested release after documented review."})
    finally:
        app.dependency_overrides.clear()
    assert edit.status_code == 409
    assert release.status_code == 200 and release.json()["do_not_call"] is False
    event = next(row for row in session.added if isinstance(row, DoNotCallEvent))
    assert event.action == "released" and event.reason


def test_demo_verification_fixture_is_admin_only_and_fictional_only():
    customer_id = uuid.uuid4()
    customer = Customer(id=customer_id, customer_ref="DEMO-0005", display_name="Demo Customer Five", birth_year=1990,
                        preferred_language="en", do_not_call=False, verification_status="unverified",
                        created_at=datetime.now(timezone.utc))
    class Session:
        def get(self, model, key): return customer if model is Customer and key == customer_id else None
    app.dependency_overrides[get_db] = lambda: Session()
    try:
        anonymous = TestClient(app).get(f"/api/customers/{customer_id}/demo-verification-fixture")
        admin = client.get(f"/api/customers/{customer_id}/demo-verification-fixture")
    finally:
        app.dependency_overrides.clear()
    assert anonymous.status_code == 401
    assert admin.status_code == 200
    assert admin.json() == {"customer_ref": "DEMO-0005", "display_name": "Demo Customer Five", "birth_year": 1990, "demo_only": True}


def test_new_customer_reporting_and_export_routes_require_authentication():
    unauthenticated = TestClient(app)
    assert unauthenticated.post(
        "/api/customers/import/preview",
        files={"file": ("customers.csv", "customer_ref,display_name,birth_year\nDEV-1,Asha,1980\n", "text/csv")},
    ).status_code == 401
    assert unauthenticated.post("/api/customers", json={"customer_ref": "DEV-1", "display_name": "Asha", "birth_year": 1980}).status_code == 401
    assert unauthenticated.get("/api/reports/calls").status_code == 401
    assert unauthenticated.get("/api/reports/calls.csv").status_code == 401
    call_id = "00000000-0000-0000-0000-000000000001"
    assert unauthenticated.get(f"/api/calls/{call_id}/transcript").status_code == 401
    assert unauthenticated.get(f"/api/calls/{call_id}/summary").status_code == 401
    assert unauthenticated.post(f"/api/calls/{call_id}/summary/retry").status_code == 401
    assert unauthenticated.get(f"/api/calls/{call_id}/callbacks").status_code == 401


def test_authenticated_admin_can_access_protected_endpoint():
    class EmptyRows:
        def all(self):
            return []

    class EmptySession:
        def scalar(self, *_args, **_kwargs):
            return 0

        def scalars(self, *_args, **_kwargs):
            return EmptyRows()

    app.dependency_overrides[get_db] = lambda: EmptySession()
    try:
        response = client.get("/api/calls")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200


def test_outbound_workflow_records_are_disabled_by_default(monkeypatch):
    class EmptySession:
        def get(self, *_args, **_kwargs):
            raise AssertionError("A customer is not required before the disabled check")

    monkeypatch.setattr("app.main.settings.outbound_calling_enabled", False)
    app.dependency_overrides[get_db] = lambda: EmptySession()
    try:
        response = client.post("/api/calls", json={"direction": "outbound", "customer_id": str(uuid.uuid4())})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 409
    assert "disabled" in response.json()["detail"].lower()


def test_call_export_has_only_permitted_columns():
    class EmptyRows:
        def all(self):
            return []

    class EmptySession:
        def scalars(self, *_args, **_kwargs):
            return EmptyRows()

    app.dependency_overrides[get_db] = lambda: EmptySession()
    try:
        response = client.get("/api/reports/calls.csv")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.text.strip() == "call_id,customer_reference,direction,status,outcome,started_at,ended_at,duration_seconds,callback_requested"
    assert "birth_year" not in response.text
    assert "financial" not in response.text.lower()

