from datetime import date, datetime, timedelta
import uuid

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import CallOutcome


class CustomerOut(BaseModel):
    id: uuid.UUID
    customer_ref: str
    display_name: str
    phone_last4: str | None
    preferred_language: str = "en"
    verification_status: str
    outbound_consent_at: datetime | None = None
    consent_source: str | None = None
    do_not_call: bool = False
    birth_year_available: bool = False
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CustomerWrite(BaseModel):
    customer_ref: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    display_name: str = Field(min_length=1, max_length=120)
    birth_year: int = Field(ge=1900, le=date.today().year)
    preferred_language: Literal["en", "hi"] = "en"
    outbound_consent_at: datetime | None = None
    consent_source: str | None = Field(default=None, max_length=120)
    do_not_call: bool = False

    @field_validator("outbound_consent_at")
    @classmethod
    def consent_datetime_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Consent timestamp must include a timezone.")
        if value is not None and value > datetime.now(value.tzinfo):
            raise ValueError("Consent timestamp cannot be in the future.")
        return value

    @model_validator(mode="after")
    def consent_evidence_pair(self):
        fields_set = self.model_fields_set
        if ("outbound_consent_at" in fields_set) != ("consent_source" in fields_set):
            raise ValueError("Consent timestamp and evidence source must be supplied together.")
        if bool(self.outbound_consent_at) != bool(self.consent_source):
            raise ValueError("Consent timestamp and evidence source must be supplied together.")
        return self

    @field_validator("customer_ref")
    @classmethod
    def normalize_ref(cls, value: str) -> str:
        return value.upper()

    @field_validator("display_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned or any(ord(char) < 32 for char in cleaned):
            raise ValueError("Name is required and cannot contain control characters.")
        return cleaned


class CallCreate(BaseModel):
    customer_id: uuid.UUID | None = None
    direction: str = Field(default="inbound", pattern="^(inbound|outbound)$")
    callback_requested: bool = False

    @model_validator(mode="after")
    def outbound_requires_customer(self):
        if self.direction == "outbound" and self.customer_id is None:
            raise ValueError("Outbound workflow requests require a linked customer.")
        return self


class CallOutcomeUpdate(BaseModel):
    outcome: CallOutcome


class CallLifecycleUpdate(BaseModel):
    status: Literal["completed", "failed", "disconnected"]


class CallLifecycleEventOut(BaseModel):
    event_type: str
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CustomerVerificationRequest(BaseModel):
    display_name: str | None = None
    birth_year: str | None = None


class CustomerVerificationResult(BaseModel):
    verified: bool
    message: str


class ImportRowError(BaseModel):
    row: int
    field: str
    message: str


class CustomerImportResult(BaseModel):
    total_rows: int
    imported_rows: int
    duplicate_rows: int
    rejected_rows: int
    errors: list[ImportRowError]
    errors_truncated: bool


class CallOut(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID | None
    status: str
    outcome: CallOutcome | None
    direction: str
    started_at: datetime
    ended_at: datetime | None
    callback_requested: bool
    customer_ref: str | None = None
    customer_display_name: str | None = None
    verification_status: str | None = None
    duration_seconds: int | None = None
    transcript_available: bool = False
    summary: str | None = None
    simulated: bool = True
    channel: str = "operational_record"
    voice_state: str = "new"
    verification_attempts: int = 0
    voice_verified: bool = False
    callback_status: str | None = None
    model_config = ConfigDict(from_attributes=True)


class VoiceSessionCreate(BaseModel):
    customer_id: uuid.UUID
    language: Literal["en", "hi"] = "en"


class VoiceTurnInput(BaseModel):
    turn_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    text: str = Field(min_length=1, max_length=1200)
    language: Literal["en", "hi"]


class VoiceMetricInput(BaseModel):
    turn_id: uuid.UUID
    utterance_ended_at: datetime
    recognition_completed_at: datetime
    request_started_at: datetime
    response_received_at: datetime
    speech_started_at: datetime

    @field_validator("utterance_ended_at", "recognition_completed_at", "request_started_at", "response_received_at", "speech_started_at")
    @classmethod
    def timestamps_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("Voice timing timestamps must include a timezone.")
        return value


class DoNotCallRelease(BaseModel):
    reason: str = Field(min_length=20, max_length=500)

    @field_validator("reason")
    @classmethod
    def reason_must_be_meaningful(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 20:
            raise ValueError("Provide an authorized release reason of at least 20 characters.")
        return normalized


class Page(BaseModel):
    items: list
    total: int
    limit: int
    offset: int


class CallbackCreate(BaseModel):
    scheduled_at: datetime | None = None
    timezone_name: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=250)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("scheduled_at")
    @classmethod
    def scheduled_datetime_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            _validate_callback_schedule(value)
        return value

    @field_validator("timezone_name")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        return _validate_timezone_name(value)


class CallbackUpdate(BaseModel):
    status: Literal["scheduled", "completed", "cancelled", "missed"]
    scheduled_at: datetime | None = None
    timezone_name: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=250)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("scheduled_at")
    @classmethod
    def update_datetime_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            _validate_callback_schedule(value)
        return value

    @field_validator("timezone_name")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        return _validate_timezone_name(value)

    @model_validator(mode="after")
    def scheduled_status_requires_time(self):
        if self.status == "scheduled" and self.scheduled_at is None:
            raise ValueError("A scheduled callback requires a scheduled time.")
        return self


class CallbackEventOut(BaseModel):
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


def _validate_callback_schedule(value: datetime) -> None:
    if value.utcoffset() is None:
        raise ValueError("Scheduled time must include a timezone.")
    now = datetime.now(value.tzinfo)
    if value <= now:
        raise ValueError("Scheduled callback must be in the future.")
    if value > now + timedelta(days=90):
        raise ValueError("Scheduled callback must be within 90 days.")


def _validate_timezone_name(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Provide a valid IANA timezone name.") from exc
    return value


class CallbackOut(BaseModel):
    id: uuid.UUID
    call_id: uuid.UUID
    status: str
    scheduled_at: datetime | None
    timezone_name: str | None = None
    reason: str | None = None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    history: list[CallbackEventOut] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class VerificationEventOut(BaseModel):
    verified: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TranscriptMessageOut(BaseModel):
    speaker: str
    content: str
    provenance: str
    language: str | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CallSummaryOut(BaseModel):
    status: Literal["unavailable", "pending", "completed", "failed"]
    content: str | None = None
    provenance: str | None = None
    attempts: int = 0
    error_code: str | None = None
    updated_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)

