import pytest
from pydantic import ValidationError

from app.schemas.api import CallbackCreate, CallbackUpdate, CustomerWrite


def test_outbound_consent_requires_timestamp_and_evidence_source():
    with pytest.raises(ValidationError):
        CustomerWrite(customer_ref="DEV-1", display_name="Asha", birth_year=1980, outbound_consent_at="2026-10-30T10:00:00+05:30")
    with pytest.raises(ValidationError):
        CustomerWrite(customer_ref="DEV-1", display_name="Asha", birth_year=1980, consent_source="written form")


def test_callback_schedule_requires_timezone_and_status_time():
    with pytest.raises(ValidationError):
        CallbackCreate(scheduled_at="2026-11-02T10:00:00")
    with pytest.raises(ValidationError):
        CallbackUpdate(status="scheduled")
    valid = CallbackUpdate(status="scheduled", scheduled_at="2026-11-02T10:00:00+05:30", timezone_name="Asia/Kolkata")
    assert valid.scheduled_at.utcoffset().total_seconds() == 19800
    with pytest.raises(ValidationError):
        CallbackCreate(scheduled_at="2026-10-30T10:00:00+05:30")
    with pytest.raises(ValidationError):
        CallbackUpdate(status="scheduled", scheduled_at="2026-11-02T10:00:00+05:30", timezone_name="Not/AZone")
