import uuid

import pytest

from app.models import Call, CallOutcome, CallStatus, CallbackFollowUp, CallbackFollowUpEvent
from app.services.call_records import persist_summary, persist_transcript, record_call_outcome


class RecordingSession:
    def __init__(self, scalars=()):
        self.added = []
        self.scalar_results = iter(scalars)

    def add(self, item):
        self.added.append(item)

    def scalar(self, _statement):
        return next(self.scalar_results)


def test_transcript_storage_rejects_simulated_calls_and_invalid_provenance():
    session = RecordingSession()
    simulated = Call(id=uuid.uuid4(), simulated=True)
    with pytest.raises(ValueError, match="Simulated|simulated"):
        persist_transcript(session, simulated, [("customer", "Hello")], "human_review", "en")
    real = Call(id=uuid.uuid4(), simulated=False)
    with pytest.raises(ValueError, match="provenance"):
        persist_transcript(session, real, [("customer", "Hello")], "unknown", "en")
    assert session.added == []


def test_summary_requires_transcript_and_has_provenance():
    real = Call(id=uuid.uuid4(), simulated=False)
    with pytest.raises(ValueError, match="transcript"):
        persist_summary(RecordingSession([None]), real, "One\nTwo\nThree", "provider:local")
    session = RecordingSession([uuid.uuid4(), None])
    summary = persist_summary(session, real, "One\nTwo\nThree", "human_review")
    assert summary.status == "completed"
    assert summary.provenance == "human_review"
    assert summary.content == "One\nTwo\nThree"


def test_local_simulation_transcript_and_three_line_summary_are_persistable():
    call = Call(id=uuid.uuid4(), simulated=True)
    session = RecordingSession([uuid.uuid4(), None])
    persist_transcript(session, call, [("assistant", "Disclosure"), ("customer", "[redacted]")], "local_simulation", "en")
    summary = persist_summary(session, call, "A respondent answered; details redacted.\nIdentity verification was not attempted.\nFinal outcome: Wrong number. No callback was requested.", "local_simulation")
    assert len([row for row in session.added if row.__class__.__name__ == "TranscriptMessage"]) == 2
    assert len(summary.content.splitlines()) == 3


def test_browser_voice_transcript_requires_matching_simulated_channel():
    session = RecordingSession()
    call = Call(id=uuid.uuid4(), simulated=True, channel="browser_voice")
    persist_transcript(session, call, [("customer", "Hello")], "browser_voice", "en")
    assert session.added[0].provenance == "browser_voice"
    with pytest.raises(ValueError, match="browser voice call"):
        persist_transcript(session, Call(id=uuid.uuid4(), simulated=True), [("customer", "Hello")], "browser_voice", "en")


def test_summary_rejects_non_three_line_content():
    with pytest.raises(ValueError, match="exactly three lines"):
        persist_summary(RecordingSession([uuid.uuid4()]), Call(id=uuid.uuid4(), simulated=False), "One line", "human_review")


def test_callback_outcome_creates_one_pending_follow_up_and_reuses_existing():
    call = Call(id=uuid.uuid4(), simulated=False)
    session = RecordingSession([None, uuid.uuid4()])

    record_call_outcome(session, call, CallOutcome.callback_requested)
    record_call_outcome(session, call, CallOutcome.callback_requested)

    assert call.callback_requested is True
    assert call.outcome == CallOutcome.callback_requested
    assert sum(isinstance(row, CallbackFollowUp) for row in session.added) == 1
    assert sum(isinstance(row, CallbackFollowUpEvent) for row in session.added) == 1


def test_callback_outcome_persists_requested_schedule_without_a_second_query():
    from datetime import datetime, timezone
    scheduled_at = datetime(2026, 11, 2, 10, tzinfo=timezone.utc)
    session = RecordingSession([None])
    call = Call(id=uuid.uuid4(), simulated=True)
    record_call_outcome(session, call, CallOutcome.callback_requested, scheduled_at=scheduled_at)
    followup = next(row for row in session.added if isinstance(row, CallbackFollowUp))
    assert followup.status == "scheduled"
    assert followup.scheduled_at == scheduled_at
    assert next(row for row in session.added if isinstance(row, CallbackFollowUpEvent)).status == "scheduled"


@pytest.mark.parametrize(("outcome", "expected_status"), [
    (CallOutcome.right_customer, CallStatus.completed),
    (CallOutcome.wrong_number, CallStatus.completed),
    (CallOutcome.third_party_answered, CallStatus.completed),
    (CallOutcome.callback_requested, CallStatus.completed),
    (CallOutcome.verification_failed, CallStatus.completed),
    (CallOutcome.not_connected, CallStatus.failed),
])
def test_outcome_sets_a_consistent_terminal_call_status(outcome, expected_status):
    call = Call(id=uuid.uuid4(), simulated=True)
    session = RecordingSession([None])
    record_call_outcome(session, call, outcome)
    assert call.status == expected_status
    assert call.ended_at is not None
