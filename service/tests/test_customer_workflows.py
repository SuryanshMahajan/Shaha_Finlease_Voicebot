import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.models import Customer
from app.services.customer_import import CsvFormatError, parse_customer_csv
from tests.security_helpers import admin_headers


class ScalarRows:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class ImportSession:
    def __init__(self, existing_refs=()):
        self.customer_refs = set(existing_refs)
        self.committed = False
        self.added = []

    def scalars(self, statement):
        return ScalarRows(list(self.customer_refs))

    def add(self, customer):
        self.added.append(customer)
        self.customer_refs.add(customer.customer_ref)

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("Unexpected database rollback")


class VerificationSession:
    def __init__(self, customer):
        self.customer = customer
        self.committed = False
        self.events = []

    def scalar(self, _statement):
        return self.customer

    def add(self, event):
        self.events.append(event)

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("Unexpected database rollback")


def install_session(session):
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app, headers=admin_headers())


def test_csv_import_normalizes_values_and_deduplicates_rows():
    parsed = parse_customer_csv(
        b"customer_ref,display_name,birth_year,phone\n"
        b" ab-12 ,  Asha   Devi  ,1980,+91 (98765) 43210\n"
        b"AB-12,Asha Devi,1980,9876543210\n"
    )

    assert parsed.total_rows == 2
    assert parsed.duplicate_rows == 1
    assert parsed.rejected_rows == 0
    assert parsed.rows[0].customer_ref == "AB-12"
    assert parsed.rows[0].display_name == "Asha Devi"
    assert parsed.rows[0].phone_last4 == "3210"


@pytest.mark.parametrize(
    "content, message",
    [
        (b"", "empty"),
        (b"display_name,birth_year\nAsha,1980\n", "Missing required columns"),
        (b"customer_ref,customer_ref,display_name,birth_year\nA,A,Asha,1980\n", "duplicate column"),
        (b"customer_ref,display_name,birth_year,loan_amount\nA,Asha,1980,10\n", "Unsupported columns"),
        (b"customer_ref,display_name,birth_year\nA,\"broken,1980", "malformed"),
    ],
)
def test_csv_import_rejects_malformed_structure(content, message):
    with pytest.raises(CsvFormatError, match=message):
        parse_customer_csv(content)


def test_import_endpoint_reports_import_duplicate_and_rejected_rows():
    session = ImportSession(existing_refs={"DB-EXISTING"})
    client = install_session(session)
    content = (
        "customer_ref,display_name,birth_year,phone\n"
        "A-100,Asha Devi,1980,9876543210\n"
        "a-100,Duplicate,1980,9876543210\n"
        "B-200,Invalid Year,20xx,9876543210\n"
        "DB-EXISTING,Already There,1981,9876543210\n"
    )
    try:
        response = client.post(
            "/api/customers/import",
            files={"file": ("customers.csv", content, "text/csv")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "total_rows": 4,
        "imported_rows": 1,
        "duplicate_rows": 2,
        "rejected_rows": 1,
        "errors": [
            {
                "row": 4,
                "field": "birth_year",
                "message": "Enter a four-digit birth year.",
            }
        ],
        "errors_truncated": False,
    }
    assert session.committed
    assert "A-100" in session.customer_refs
    assert "B-200" not in session.customer_refs


def test_import_endpoint_rejects_oversized_upload_without_database_write():
    session = ImportSession()
    client = install_session(session)
    try:
        response = client.post(
            "/api/customers/import",
            files={"file": ("customers.csv", b"x" * (2 * 1024 * 1024 + 1), "text/csv")},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 413
    assert not session.committed


def test_import_preview_finds_database_duplicates_and_omits_birth_year():
    class PreviewSession:
        def scalars(self, _statement):
            return ScalarRows(["EXISTS-1"])

    app.dependency_overrides[get_db] = lambda: PreviewSession()
    client = TestClient(app, headers=admin_headers())
    content = "customer_ref,display_name,birth_year,phone\nEXISTS-1,Asha Devi,1980,9876543210\nNEW-1,Meera Shah,1985,9876543211\n"
    try:
        response = client.post("/api/customers/import/preview", files={"file": ("customers.csv", content, "text/csv")})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["ready_rows"] == 1
    assert body["duplicate_rows"] == 1
    assert body["preview"][0]["customer_ref"] == "NEW-1"
    assert "birth_year" not in response.text


def _verification_client(customer):
    return install_session(VerificationSession(customer))


def _verification_payload(client, customer_id, payload):
    return client.post(f"/api/customers/{customer_id}/verify", json=payload)


def test_identity_verification_success_normalizes_name_and_updates_status():
    customer = Customer(
        id=uuid.uuid4(), customer_ref="TEST-1", display_name="Asha Devi", birth_year=1980,
        phone_last4="3210", verification_status="unverified",
    )
    session = VerificationSession(customer)
    client = install_session(session)
    try:
        response = _verification_payload(
            client,
            customer.id,
            {"display_name": "  ASHA   DEVI ", "birth_year": "1980"},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"verified": True, "message": "Customer verified."}
    assert customer.verification_status == "verified"
    assert len(session.events) == 1 and session.events[0].verified is True
    assert session.committed
    assert "birth_year" not in response.json()


def test_identity_verification_supports_normalized_unicode_names():
    customer = Customer(
        id=uuid.uuid4(), customer_ref="TEST-UNICODE", display_name="José Ångström", birth_year=1986,
        phone_last4=None, verification_status="unverified",
    )
    client = install_session(VerificationSession(customer))
    try:
        response = _verification_payload(
            client,
            customer.id,
            {"display_name": "  JOSÉ   åNGSTRÖM ", "birth_year": "1986"},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["verified"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {"display_name": "Wrong Name", "birth_year": "1980"},
        {"display_name": "Asha Devi", "birth_year": "1981"},
        {"display_name": "Asha Devi"},
        {"birth_year": "1980"},
        {},
    ],
)
def test_identity_verification_failures_are_generic(payload):
    customer = Customer(
        id=uuid.uuid4(), customer_ref="TEST-2", display_name="Asha Devi", birth_year=1980,
        phone_last4=None, verification_status="unverified",
    )
    session = VerificationSession(customer)
    client = install_session(session)
    try:
        response = _verification_payload(client, customer.id, payload)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"verified": False, "message": "Unable to verify customer."}
    assert len(session.events) == 1 and session.events[0].verified is False
    assert customer.verification_status == "unverified"


def test_nonexistent_customer_verification_has_same_generic_failure():
    client = _verification_client(None)
    try:
        response = _verification_payload(
            client,
            uuid.uuid4(),
            {"display_name": "Asha Devi", "birth_year": "1980"},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"verified": False, "message": "Unable to verify customer."}


def test_legacy_customer_without_birth_year_is_never_verified():
    customer = Customer(
        id=uuid.uuid4(), customer_ref="LEGACY", display_name="Asha Devi", birth_year=None,
        phone_last4=None, verification_status="unverified",
    )
    client = _verification_client(customer)
    try:
        response = _verification_payload(client, customer.id, {"display_name": "Asha Devi", "birth_year": "1980"})
    finally:
        app.dependency_overrides.clear()
    assert response.json() == {"verified": False, "message": "Unable to verify customer."}
    assert customer.verification_status == "unverified"


def test_verification_is_rate_limited(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "settings", main.settings.model_copy(update={"verification_rate_limit_per_minute": 1}))
    customer = Customer(
        id=uuid.uuid4(), customer_ref="RATE", display_name="Asha Devi", birth_year=1980,
        phone_last4=None, verification_status="unverified",
    )
    client = _verification_client(customer)
    try:
        payload = {"display_name": "Wrong", "birth_year": "1980"}
        assert _verification_payload(client, customer.id, payload).status_code == 200
        limited = _verification_payload(client, customer.id, payload)
    finally:
        app.dependency_overrides.clear()
    assert limited.status_code == 429
    assert limited.headers["retry-after"]
