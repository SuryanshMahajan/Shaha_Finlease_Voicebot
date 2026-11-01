import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Call, CallOutcome, CallStatus, Customer
from tests.security_helpers import admin_headers


def test_demo_suite_persists_each_of_six_outcomes_twice(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "settings", main_module.settings.model_copy(update={"app_env": "test"}))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        for index in range(1, 7):
            session.add(Customer(
                id=uuid.uuid4(), customer_ref=f"DEMO-{index:04}", display_name=f"Demo Customer {index}",
                birth_year=1980 + index, preferred_language="en", do_not_call=False,
                verification_status="unverified", created_at=now,
            ))
        session.commit()

    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = session_override
    try:
        response = TestClient(app, headers=admin_headers()).post("/api/demo/run-suite")
        assert response.status_code == 200
        assert response.json()["created"] == 12
        dashboard = TestClient(app, headers=admin_headers()).get("/api/analytics/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["successful_verifications"] == 2
        assert dashboard.json()["verification_events_failed"] == 2
        assert dashboard.json()["outcomes"] == {outcome.value: 2 for outcome in CallOutcome}
        report = TestClient(app, headers=admin_headers()).get("/api/reports/calls")
        assert report.status_code == 200
        assert report.json()["total_calls"] == 12
        assert report.json()["verification_successes"] == 2
        assert report.json()["verification_failures"] == 2
        assert report.json()["callbacks_scheduled"] == 2
        export = TestClient(app, headers=admin_headers()).get("/api/reports/calls.csv")
        assert export.status_code == 200
        assert export.text.splitlines()[0] == "call_id,customer_reference,direction,status,outcome,started_at,ended_at,duration_seconds,callback_requested"
        assert len(export.text.splitlines()) == 13
        with Session(engine) as session:
            calls = session.scalars(select(Call).order_by(Call.started_at, Call.id)).all()
            counts = {outcome: sum(call.outcome == outcome for call in calls) for outcome in CallOutcome}
            assert len(calls) == 12
            assert set(counts.values()) == {2}
            assert all(call.simulated for call in calls)
            assert all(call.status == (CallStatus.failed if call.outcome == CallOutcome.not_connected else CallStatus.completed) for call in calls)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
