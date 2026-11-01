import enum
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, false, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CallStatus(str, enum.Enum):
    queued = "queued"
    connected = "connected"
    completed = "completed"
    failed = "failed"
    disconnected = "disconnected"


class CallOutcome(str, enum.Enum):
    right_customer = "right_customer"
    wrong_number = "wrong_number"
    third_party_answered = "third_party_answered"
    callback_requested = "callback_requested"
    verification_failed = "verification_failed"
    not_connected = "not_connected"


CALLBACK_STATUSES = ("pending", "scheduled", "completed", "cancelled", "missed")


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("customer_ref", name="uq_customers_customer_ref"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    birth_year: Mapped[int | None] = mapped_column(nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(2), default="en", nullable=False)
    outbound_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    do_not_call: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(20), default="unverified", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    calls: Mapped[list["Call"]] = relationship(back_populates="customer")
    do_not_call_events: Mapped[list["DoNotCallEvent"]] = relationship(back_populates="customer", cascade="all, delete-orphan")

    @property
    def birth_year_available(self) -> bool:
        """Expose verification readiness without returning the answer itself."""
        return self.birth_year is not None


class Call(Base):
    __tablename__ = "calls"
    __table_args__ = (
        Index("ix_calls_started_at", "started_at"),
        Index("ix_calls_status", "status"),
        Index(
            "uq_calls_provider_call_sid", "provider_call_sid", unique=True,
            postgresql_where=text("provider_call_sid IS NOT NULL"),
            mssql_where=text("provider_call_sid IS NOT NULL"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[CallStatus] = mapped_column(
        Enum(
            CallStatus,
            name="call_status",
            native_enum=False,
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        default=CallStatus.queued,
        nullable=False,
    )
    outcome: Mapped[CallOutcome | None] = mapped_column(
        Enum(
            CallOutcome,
            name="call_outcome",
            native_enum=False,
            values_callable=lambda outcomes: [outcome.value for outcome in outcomes],
        ),
        nullable=True,
    )
    direction: Mapped[str] = mapped_column(String(12), default="inbound", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    callback_requested: Mapped[bool] = mapped_column(default=False, nullable=False)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(24), default="operational_record", server_default=text("'scripted_simulation'"), nullable=False)
    language: Mapped[str] = mapped_column(String(2), default="en", nullable=False)
    voice_state: Mapped[str] = mapped_column(String(16), default="new", server_default=text("'new'"), nullable=False)
    verification_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    voice_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    verification_name_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    verification_year_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    provider_call_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    customer: Mapped[Customer | None] = relationship(back_populates="calls")
    transcript: Mapped[list["TranscriptMessage"]] = relationship(back_populates="call", cascade="all, delete-orphan")
    callbacks: Mapped[list["CallbackFollowUp"]] = relationship(back_populates="call", cascade="all, delete-orphan")
    lifecycle_events: Mapped[list["CallLifecycleEvent"]] = relationship(back_populates="call", cascade="all, delete-orphan")
    summary_record: Mapped["CallSummary | None"] = relationship(back_populates="call", cascade="all, delete-orphan", uselist=False)


class CallLifecycleEvent(Base):
    __tablename__ = "call_lifecycle_events"
    __table_args__ = (Index("ix_call_lifecycle_call_created", "call_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    call: Mapped[Call] = relationship(back_populates="lifecycle_events")


class TranscriptMessage(Base):
    __tablename__ = "transcript_messages"
    __table_args__ = (Index("ix_transcript_call_created", "call_id", "created_at"), Index("ix_transcript_expires_at", "expires_at"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), nullable=False)
    speaker: Mapped[str] = mapped_column(String(20), nullable=False)
    # Transcript storage is intentionally not exposed by initial APIs; redact/minimize before persistence.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provenance: Mapped[str] = mapped_column(String(64), default="legacy_unknown", server_default=text("'legacy_unknown'"), nullable=False)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc) + timedelta(days=180))
    call: Mapped[Call] = relationship(back_populates="transcript")


class CallSummary(Base):
    __tablename__ = "call_summaries"
    __table_args__ = (
        UniqueConstraint("call_id", name="uq_call_summaries_call_id"),
        CheckConstraint("status IN ('pending', 'completed', 'failed')", name="ck_call_summaries_status"),
        CheckConstraint("status != 'completed' OR (content IS NOT NULL AND provenance IS NOT NULL)", name="ck_call_summaries_completed_content"),
        Index("ix_call_summaries_expires_at", "expires_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default=text("'pending'"), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(default=0, server_default=text("0"), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc) + timedelta(days=180))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    call: Mapped[Call] = relationship(back_populates="summary_record")


class VerificationEvent(Base):
    """Outcome-only verification audit; never stores submitted factors or customer ID."""
    __tablename__ = "verification_events"
    __table_args__ = (Index("ix_verification_events_created_at", "created_at"), Index("ix_verification_events_customer_id", "customer_id"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    verified: Mapped[bool] = mapped_column(nullable=False)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DoNotCallEvent(Base):
    """Append-only record of opt-out requests and separately authorized releases."""
    __tablename__ = "do_not_call_events"
    __table_args__ = (
        CheckConstraint("action IN ('requested', 'released')", name="ck_do_not_call_events_action"),
        Index("ix_do_not_call_events_customer_created", "customer_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    customer: Mapped[Customer] = relationship(back_populates="do_not_call_events")


class VoiceTurnRequest(Base):
    """Idempotent persisted result; contains no user utterance or verification factors."""
    __tablename__ = "voice_turn_requests"
    __table_args__ = (UniqueConstraint("call_id", "turn_id", name="uq_voice_turn_requests_call_turn"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), nullable=False)
    turn_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(2), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ended: Mapped[bool] = mapped_column(Boolean, nullable=False)
    verification_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class VoiceTurnMetric(Base):
    """Client lifecycle timestamps for one browser-recognized and spoken turn."""
    __tablename__ = "voice_turn_metrics"
    __table_args__ = (
        UniqueConstraint("call_id", "turn_id", name="uq_voice_turn_metrics_call_turn"),
        Index("ix_voice_turn_metrics_call_created", "call_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), nullable=False)
    turn_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    utterance_ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recognition_completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    response_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    speech_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    response_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    recognition_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    server_processing_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    synthesis_start_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CallbackFollowUp(Base):
    __tablename__ = "callback_followups"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'scheduled', 'completed', 'cancelled', 'missed')", name="ck_callback_followups_status"),
        Index("uq_callback_followups_active_call", "call_id", unique=True, postgresql_where=text("status IN ('pending', 'scheduled')"), mssql_where=text("status IN ('pending', 'scheduled')")),
        Index("ix_callback_followups_scheduled_at", "scheduled_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default=text("'pending'"), nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(250), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    call: Mapped[Call] = relationship(back_populates="callbacks")
    history: Mapped[list["CallbackFollowUpEvent"]] = relationship(back_populates="followup", cascade="all, delete-orphan", order_by="CallbackFollowUpEvent.created_at")


class CallbackFollowUpEvent(Base):
    __tablename__ = "callback_followup_events"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    followup_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("callback_followups.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    followup: Mapped[CallbackFollowUp] = relationship(back_populates="history")

