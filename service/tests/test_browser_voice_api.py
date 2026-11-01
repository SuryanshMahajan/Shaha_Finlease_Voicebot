import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Call, CallOutcome, CallSummary, Customer, TranscriptMessage, VerificationEvent, VoiceTurnRequest
from tests.security_helpers import admin_headers


def test_browser_voice_session_persists_redacted_verification_and_summary():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    customer_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(Customer(id=customer_id, customer_ref="DEMO-0005", display_name="Demo Customer Five", birth_year=1990,
                             preferred_language="en", do_not_call=False, verification_status="unverified",
                             created_at=datetime.now(timezone.utc)))
        session.commit()

    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = session_override
    client = TestClient(app, headers=admin_headers())
    try:
        start = client.post("/api/voice-sessions", json={"customer_id": str(customer_id), "language": "en"})
        assert start.status_code == 201
        call_id = uuid.UUID(start.json()["call_id"])
        assert start.json()["simulated"] is True
        assert "simulated conversation" in start.json()["greeting"]
        base = datetime.now(timezone.utc)
        stamp_values = [base + timedelta(milliseconds=step) for step in (0, 40, 50, 180, 320)]
        metric = client.post(f"/api/voice-sessions/{call_id}/metrics", json={
            "turn_id": str(uuid.uuid4()),
            "utterance_ended_at": stamp_values[0].isoformat(),
            "recognition_completed_at": stamp_values[1].isoformat(),
            "request_started_at": stamp_values[2].isoformat(),
            "response_received_at": stamp_values[3].isoformat(),
            "speech_started_at": stamp_values[4].isoformat(),
        })
        assert metric.status_code == 201 and metric.json()["response_latency_ms"] == 320
        prompt_payload = {"turn_id": str(uuid.uuid4()), "text": "verify", "language": "en"}
        prompt = client.post(f"/api/voice-sessions/{call_id}/turn", json=prompt_payload)
        assert prompt.status_code == 200
        replay = client.post(f"/api/voice-sessions/{call_id}/turn", json=prompt_payload)
        assert replay.status_code == 200 and replay.json() == prompt.json()
        failed = client.post(f"/api/voice-sessions/{call_id}/turn", json={"text": "My name is Demo Customer Five and my birth year is 1991", "language": "en"})
        assert failed.status_code == 200 and failed.json()["state"] == "verifying"
        success = client.post(f"/api/voice-sessions/{call_id}/turn", json={"text": "My name is Demo Customer Five and my birth year is 1990", "language": "en"})
        assert success.status_code == 200 and success.json()["outcome"] == CallOutcome.right_customer.value
        end = client.post(f"/api/voice-sessions/{call_id}/end")
        assert end.status_code == 200
        with Session(engine) as session:
            call = session.get(Call, call_id)
            verification_events = session.scalars(select(VerificationEvent).where(VerificationEvent.call_id == call_id)).all()
            transcript = session.scalars(select(TranscriptMessage).where(TranscriptMessage.call_id == call_id)).all()
            turn_requests = session.scalars(select(VoiceTurnRequest).where(VoiceTurnRequest.call_id == call_id)).all()
            summary = session.scalar(select(CallSummary).where(CallSummary.call_id == call_id))
            assert call and call.simulated and call.channel == "browser_voice" and call.voice_verified
            assert call.outcome == CallOutcome.right_customer and call.verification_attempts == 2
            assert [event.verified for event in verification_events] == [False, True]
            assert len(turn_requests) == 3
            assert len([message for message in transcript if message.speaker == "customer" and message.content == "verify"]) == 1
            assert all("1991" not in message.content and "1990" not in message.content for message in transcript)
            assert any("verification response redacted" in message.content for message in transcript)
            assert summary and len(summary.content.splitlines()) == 3

        exact_start = client.post("/api/voice-sessions", json={"customer_id": str(customer_id), "language": "en"})
        exact_id = uuid.UUID(exact_start.json()["call_id"])
        exact_turn = client.post(f"/api/voice-sessions/{exact_id}/turn", json={
            "text": "My name is Demo Customer Five and my birth year is 1990.", "language": "en",
        })
        assert exact_turn.status_code == 200 and exact_turn.json()["outcome"] == CallOutcome.right_customer.value
        client.post(f"/api/voice-sessions/{exact_id}/end")

        partial_start = client.post("/api/voice-sessions", json={"customer_id": str(customer_id), "language": "en"})
        partial_id = uuid.UUID(partial_start.json()["call_id"])
        name_only = client.post(f"/api/voice-sessions/{partial_id}/turn", json={"text": "My name is Demo Customer Five", "language": "en"})
        assert "four-digit birth year" in name_only.json()["response"]
        year_only = client.post(f"/api/voice-sessions/{partial_id}/turn", json={"text": "1990", "language": "en"})
        assert year_only.status_code == 200 and year_only.json()["outcome"] == CallOutcome.right_customer.value
        client.post(f"/api/voice-sessions/{partial_id}/end")
        with Session(engine) as session:
            exact_transcript = session.scalars(select(TranscriptMessage).where(TranscriptMessage.call_id == exact_id)).all()
            partial_call = session.get(Call, partial_id)
            partial_transcript = session.scalars(select(TranscriptMessage).where(TranscriptMessage.call_id == partial_id)).all()
            assert partial_call and partial_call.verification_attempts == 1
            assert all("Demo Customer Five" not in row.content and "1990" not in row.content for row in exact_transcript + partial_transcript)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
