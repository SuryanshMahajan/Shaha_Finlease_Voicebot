import uuid
from datetime import datetime, timezone

import pytest

from app.db.session import get_db
from app.main import app
from app.models import Call, CallStatus, Customer
from app.services.outbound import calling_window_open
from tests.security_helpers import admin_headers
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "instant,expected",
    [
        (datetime(2026, 10, 31, 2, 29, tzinfo=timezone.utc), False),
        (datetime(2026, 10, 31, 2, 30, tzinfo=timezone.utc), True),
        (datetime(2026, 10, 31, 13, 30, tzinfo=timezone.utc), True),
        (datetime(2026, 10, 31, 13, 30, 0, tzinfo=timezone.utc), True),
        (datetime(2026, 10, 31, 13, 30, 0, 1, tzinfo=timezone.utc), False),
        (datetime(2026, 10, 31, 13, 30, 1, tzinfo=timezone.utc), False),
        (datetime(2026, 10, 31, 13, 31, tzinfo=timezone.utc), False),
    ],
)
def test_calling_window_uses_timezone_minute_boundaries(instant, expected):
    assert calling_window_open(instant, "Asia/Kolkata", 8, 19) is expected


def test_calling_window_rejects_naive_datetime():
    with pytest.raises(ValueError, match="timezone-aware"):
        calling_window_open(datetime(2026, 10, 31, 10), "Asia/Kolkata", 8, 19)


def test_blocked_outbound_window_creates_no_call_record(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "settings", main.settings.model_copy(update={
        "outbound_calling_enabled": True,
        "calling_timezone": "Asia/Kolkata",
        "calling_hour_start": 8,
        "calling_hour_end": 19,
    }))
    monkeypatch.setattr(main, "utc_now", lambda: datetime(2026, 10, 31, 2, 29, tzinfo=timezone.utc))
    customer_id = uuid.uuid4()
    customer = Customer(id=customer_id, customer_ref="SAFE-CLOCK", display_name="Demo User", birth_year=1980,
                        outbound_consent_at=datetime(2026, 10, 1, tzinfo=timezone.utc), consent_source="synthetic fixture")

    class Session:
        added = []
        def get(self, model, _id): return customer if model is Customer else None
        def add(self, row): self.added.append(row)
        def commit(self): raise AssertionError("Blocked attempts must not commit")

    session = Session()
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = TestClient(app, headers=admin_headers()).post(
            "/api/calls", json={"direction": "outbound", "customer_id": str(customer_id)}
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403
    assert "calling window" in response.json()["detail"]
    assert session.added == []


@pytest.mark.parametrize("has_consent,do_not_call,expected_status", [(False, False, 403), (True, True, 403), (True, False, 201)])
def test_outbound_record_requires_consent_and_allows_dnc_block(monkeypatch, has_consent, do_not_call, expected_status):
    import app.main as main

    monkeypatch.setattr(main, "settings", main.settings.model_copy(update={
        "outbound_calling_enabled": True,
        "calling_timezone": "Asia/Kolkata",
        "calling_hour_start": 0,
        "calling_hour_end": 24,
    }))
    customer_id = uuid.uuid4()
    customer = Customer(
        id=customer_id,
        customer_ref="SAFE-1",
        display_name="Synthetic User",
        birth_year=1980,
        outbound_consent_at=datetime(2026, 10, 1, tzinfo=timezone.utc) if has_consent else None,
        consent_source="test fixture" if has_consent else None,
        do_not_call=do_not_call,
    )

    class Session:
        def __init__(self): self.added = []
        def get(self, model, _id): return customer if model is Customer else None
        def add(self, row): self.added.append(row)
        def flush(self):
            for row in self.added:
                if isinstance(row, Call):
                    if row.id is None:
                        row.id = uuid.uuid4()
                    if row.started_at is None:
                        row.started_at = datetime.now(timezone.utc)
                    if row.status is None:
                        row.status = CallStatus.queued
                    if row.callback_requested is None:
                        row.callback_requested = False
        def commit(self): pass
        def refresh(self, _row): pass

    session = Session()
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = TestClient(app, headers=admin_headers()).post(
            "/api/calls", json={"direction": "outbound", "customer_id": str(customer_id)}
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == expected_status
    if response.status_code == 201:
        assert response.json()["simulated"] is True
        assert "telephone call" not in response.text.lower()
