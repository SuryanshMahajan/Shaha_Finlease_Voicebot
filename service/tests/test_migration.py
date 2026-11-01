from importlib import import_module

from app.models import Call, CallLifecycleEvent, CallOutcome, CallStatus, VerificationEvent


def test_migration_enum_matches_model_without_implicit_creation():
    migration = import_module("migrations.versions.0001_initial")
    model_enum = Call.__table__.c.status.type

    assert model_enum.enums == [status.value for status in CallStatus]
    assert migration.call_status.enums == model_enum.enums
    assert migration.call_status.create_type is False


def test_call_outcome_migration_matches_model_enum():
    migration = import_module("migrations.versions.0002_customer_import_verification_outcomes")
    model_enum = Call.__table__.c.outcome.type

    assert model_enum.enums == [outcome.value for outcome in CallOutcome]
    assert migration.call_outcome.enums == model_enum.enums
    assert migration.call_outcome.create_type is False
    assert [status.value for status in CallStatus] == ["queued", "connected", "completed", "failed", "disconnected"]


def test_verification_event_migration_is_additive_and_minimizes_data():
    migration = import_module("migrations.versions.0003_verification_events")
    assert migration.down_revision == "0002_customer_workflow"
    privacy_migration = import_module("migrations.versions.0004_callback_privacy_metadata")
    assert privacy_migration.down_revision == migration.revision
    assert set(VerificationEvent.__table__.columns.keys()) == {"id", "verified", "simulated", "created_at", "customer_id", "call_id"}
    assert "submitted_answer" not in VerificationEvent.__table__.columns


def test_call_lifecycle_migration_is_additive_and_matches_model():
    migration = import_module("migrations.versions.0005_call_lifecycle_events")
    assert migration.down_revision == "0004_callback_privacy"
    assert set(CallLifecycleEvent.__table__.columns.keys()) == {"id", "call_id", "event_type", "status", "created_at"}


def test_twilio_migration_adds_provider_sid_without_customer_phone_fields():
    migration = import_module("migrations.versions.0006_twilio_relay_metadata")
    assert migration.down_revision == "0005_call_lifecycle_events"
    assert "provider_call_sid" in Call.__table__.columns
    assert "phone" not in Call.__table__.columns


def test_provider_sid_uses_nullable_filtered_unique_index():
    index = next(index for index in Call.__table__.indexes if index.name == "uq_calls_provider_call_sid")
    assert index.unique is True
    assert index.dialect_options["mssql"]["where"] is not None
    assert index.dialect_options["postgresql"]["where"] is not None
    migration = import_module("migrations.versions.0008_nullable_provider_sid_index")
    assert migration.down_revision == "0007_assignment_language"


def test_browser_voice_safety_migration_is_additive_and_has_audit_tables():
    migration = import_module("migrations.versions.0009_browser_voice_safety")
    assert migration.down_revision == "0008_provider_sid_index"
    assert {"channel", "voice_state", "verification_attempts", "voice_verified", "verification_name_match", "verification_year_match"} <= set(Call.__table__.columns.keys())
    from app.models import DoNotCallEvent, VoiceTurnMetric, VoiceTurnRequest
    assert DoNotCallEvent.__tablename__ == "do_not_call_events"
    assert VoiceTurnMetric.__tablename__ == "voice_turn_metrics"
    assert VoiceTurnRequest.__tablename__ == "voice_turn_requests"
    assert {"call_id", "turn_id", "response", "language", "state", "outcome", "ended", "verification_attempts"} <= set(VoiceTurnRequest.__table__.columns.keys())
    assert "submitted_answer" not in VerificationEvent.__table__.columns


def test_followup_migration_adds_factor_state_and_turn_idempotency_additively():
    migration = import_module("migrations.versions.0010_voice_turn_idempotency")
    assert migration.down_revision == "0009_browser_voice_safety"
    assert {"verification_name_match", "verification_year_match"} <= set(Call.__table__.columns.keys())
    from app.models import CallbackFollowUp, VoiceTurnRequest
    assert {"timezone_name", "reason"} <= set(CallbackFollowUp.__table__.columns.keys())
    assert VoiceTurnRequest.__tablename__ == "voice_turn_requests"
