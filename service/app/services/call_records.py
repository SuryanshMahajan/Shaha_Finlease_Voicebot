"""Persistence helpers used only after real provider or human-reviewed data exists."""
import re
import uuid
from datetime import datetime, time, timedelta, timezone
import unicodedata
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Call, CallOutcome, CallStatus, CallSummary, CallbackFollowUp, CallbackFollowUpEvent, TranscriptMessage

_PROVENANCE = re.compile(r"^(human_review|local_simulation|browser_voice|provider:[a-z0-9_-]{1,56})$")


def record_call_outcome(
    db: Session,
    call: Call,
    outcome: CallOutcome,
    *,
    scheduled_at: datetime | None = None,
    timezone_name: str | None = None,
    reason: str | None = None,
) -> CallbackFollowUp | None:
    """Apply a structured outcome and idempotently create its callback task."""
    call.outcome = outcome
    call.callback_requested = outcome == CallOutcome.callback_requested
    if outcome == CallOutcome.not_connected:
        call.status = CallStatus.failed
    elif outcome in {CallOutcome.right_customer, CallOutcome.wrong_number, CallOutcome.third_party_answered,
                     CallOutcome.callback_requested, CallOutcome.verification_failed}:
        call.status = CallStatus.completed
    if call.status in {CallStatus.failed, CallStatus.completed} and call.ended_at is None:
        call.ended_at = datetime.now(timezone.utc)
    if not call.callback_requested:
        return None
    active = db.scalar(
        select(CallbackFollowUp).where(
            CallbackFollowUp.call_id == call.id,
            CallbackFollowUp.status.in_(["pending", "scheduled"]),
        )
    )
    if active:
        changed = False
        if scheduled_at is not None:
            active.status = "scheduled"
            active.scheduled_at = scheduled_at
            changed = True
        if timezone_name is not None:
            active.timezone_name = timezone_name
        if reason is not None:
            active.reason = reason
        if changed:
            db.add(CallbackFollowUpEvent(followup_id=active.id, status="scheduled"))
        return active
    status = "scheduled" if scheduled_at is not None else "pending"
    followup = CallbackFollowUp(
        id=uuid.uuid4(), call_id=call.id, status=status, scheduled_at=scheduled_at,
        timezone_name=timezone_name, reason=reason,
    )
    db.add(followup)
    db.add(CallbackFollowUpEvent(followup_id=followup.id, status=status))
    return followup


def parse_requested_callback_time(text: str, timezone_name: str, now: datetime | None = None) -> datetime | None:
    """Parse a narrow, explicit callback date/time phrase; unsupported text stays pending."""
    value = unicodedata.normalize("NFKC", text).translate(str.maketrans("\u0966\u0967\u0968\u0969\u096a\u096b\u096c\u096d\u096e\u096f", "0123456789")).casefold()
    zone = ZoneInfo(timezone_name)
    local_now = (now or datetime.now(timezone.utc)).astimezone(zone)
    day_match = re.search(r"\b(tomorrow|today)\b", value)
    time_match = re.search(r"\b(?:at\s*)?(\d{1,2})(?::([0-5]\d))?\s*(am|pm)?\b", value)
    if not day_match or not time_match:
        return None
    hour = int(time_match.group(1))
    minute = int(time_match.group(2) or 0)
    meridiem = time_match.group(3)
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = (hour % 12) + (12 if meridiem == "pm" else 0)
    elif hour > 23:
        return None
    callback_day = local_now.date() + timedelta(days=1 if day_match.group(1) == "tomorrow" else 0)
    candidate = datetime.combine(callback_day, time(hour, minute), zone)
    if candidate <= local_now or candidate > local_now + timedelta(days=90):
        return None
    return candidate


def persist_transcript(
    db: Session,
    call: Call,
    messages: list[tuple[str, str]],
    provenance: str,
    language: str,
) -> None:
    """Persist transcript segments with provenance appropriate to their source."""
    if call.simulated and provenance not in {"local_simulation", "browser_voice"}:
        raise ValueError("Simulated calls require an explicit simulation transcript provenance.")
    if provenance == "browser_voice" and call.channel != "browser_voice":
        raise ValueError("browser_voice provenance requires a browser voice call.")
    if not call.simulated and provenance == "local_simulation":
        raise ValueError("local_simulation provenance requires a simulated call.")
    if not _PROVENANCE.fullmatch(provenance):
        raise ValueError("Transcript provenance is invalid.")
    if language not in {"hi", "en"}:
        raise ValueError("Transcript language must be Hindi or English.")
    if not messages or len(messages) > 5000:
        raise ValueError("Transcript must contain 1 to 5000 segments.")
    for speaker, content in messages:
        if speaker not in {"assistant", "customer", "agent"} or not content.strip() or len(content) > 10_000:
            raise ValueError("Transcript segment is invalid.")
    for speaker, content in messages:
        db.add(TranscriptMessage(call_id=call.id, speaker=speaker, content=content, provenance=provenance, language=language, expires_at=datetime.now(timezone.utc) + timedelta(days=get_settings().transcript_retention_days)))


def persist_summary(db: Session, call: Call, content: str, provenance: str) -> CallSummary:
    """Store a summary only when it is grounded in persisted transcript content."""
    if call.simulated and provenance not in {"local_simulation", "browser_voice"}:
        raise ValueError("Simulated summaries require an explicit simulation summary provenance.")
    if provenance == "browser_voice" and call.channel != "browser_voice":
        raise ValueError("browser_voice provenance requires a browser voice call.")
    if not call.simulated and provenance == "local_simulation":
        raise ValueError("local_simulation provenance requires a simulated call.")
    if not _PROVENANCE.fullmatch(provenance):
        raise ValueError("Summary provenance is invalid.")
    if not content.strip() or len(content) > 5000:
        raise ValueError("Summary content is invalid.")
    if len(content.strip().splitlines()) != 3:
        raise ValueError("Summary must contain exactly three lines.")
    # SessionLocal disables autoflush, so transcript rows created moments ago
    # must be flushed before this existence check.
    flush = getattr(db, "flush", None)
    if flush is not None:
        flush()
    if not db.scalar(select(TranscriptMessage.id).where(TranscriptMessage.call_id == call.id).limit(1)):
        raise ValueError("A transcript is required before a summary can be stored.")
    summary = db.scalar(select(CallSummary).where(CallSummary.call_id == call.id))
    if summary is None:
        summary = CallSummary(id=uuid.uuid4(), call_id=call.id, status="completed", attempts=1)
        db.add(summary)
    summary.content = content.strip()
    summary.provenance = provenance
    summary.status = "completed"
    summary.error_code = None
    summary.updated_at = datetime.now(timezone.utc)
    summary.expires_at = datetime.now(timezone.utc) + timedelta(days=get_settings().transcript_retention_days)
    return summary
