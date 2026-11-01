import csv
import hmac
import io
import re
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import Date, cast, false, func, or_, select, text, true
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import audit_event, limit_request, login, require_admin, require_configured_auth
from app.db.session import get_db
from app.models import Call, CallLifecycleEvent, CallOutcome, CallStatus, Customer, VerificationEvent, CallbackFollowUp, CallbackFollowUpEvent, CallSummary, TranscriptMessage, DoNotCallEvent, VoiceTurnMetric, VoiceTurnRequest
from app.schemas.api import (
    CallCreate,
    CallOut,
    CallOutcomeUpdate,
    CallLifecycleUpdate,
    CallLifecycleEventOut,
    CustomerImportResult,
    CustomerOut,
    CustomerVerificationRequest,
    CustomerVerificationResult,
    CustomerWrite,
    CallbackCreate,
    CallbackOut,
    CallbackUpdate,
    VerificationEventOut,
    TranscriptMessageOut,
    CallSummaryOut,
    VoiceSessionCreate,
    VoiceTurnInput,
    VoiceMetricInput,
    DoNotCallRelease,
)
from app.services.customer_import import (
    MAX_IMPORT_BYTES,
    MAX_RETURNED_ERRORS,
    CsvFormatError,
    normalize_name_for_comparison,
    parse_customer_csv,
)
from app.services.voice import provider_readiness
from app.services.outbound import calling_window_open, utc_now
from app.services.call_records import parse_requested_callback_time, record_call_outcome
from app.services.call_records import persist_summary, persist_transcript
from app.services.demo import PERSONAS as DEMO_PERSONAS, SUITE_PERSONAS, run_persona, three_line_summary
from app.services.conversation import ConversationEngine, ConversationState, extract_verification_factors
from app.services.llm import safe_small_talk
from app.services.metrics import call_rates
from app.routers.twilio import relay_status, router as twilio_router

settings = get_settings()
app = FastAPI(title="Shaha Finlease Voicebot API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False, allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type", "Authorization"])
app.include_router(twilio_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}


def _local_day_bound(day: date, *, end: bool = False) -> datetime:
    boundary_time = datetime.max.time() if end else datetime.min.time()
    return datetime.combine(day, boundary_time, tzinfo=ZoneInfo(settings.calling_timezone)).astimezone(timezone.utc)


@app.get("/api/health/ready")
def readiness(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ready", "database": "connected"}


@app.get("/api/providers/status")
def providers_status(_admin: str = Depends(require_admin)):
    """Expose provider state, never credential values or environment contents."""
    return {
        "providers": [
            {"name": item.provider, "configured": item.configured, "mode": item.mode}
            for item in provider_readiness()
        ] + [
            {"name": "local_mocks", "configured": True, "mode": "simulated", "state": "simulated"},
            {"name": "gemini", "configured": settings.llm_provider == "gemini" and bool(settings.gemini_api_key), "mode": "optional", "state": "configured" if settings.llm_provider == "gemini" and settings.gemini_api_key else "unconfigured"},
            relay_status(),
        ],
        "outbound_calling_enabled": settings.outbound_calling_enabled,
        "real_calls_enabled": False,
    }


@app.post("/api/auth/login", dependencies=[Depends(require_configured_auth)])
def authenticate(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    runtime_settings: Settings = Depends(get_settings),
):
    limit_request(request, "auth", settings.auth_rate_limit_per_minute)
    token = login(form.username, form.password, runtime_settings)
    if not token:
        audit_event("authentication", "failure")
        raise HTTPException(status_code=401, detail="Invalid username or password.", headers={"WWW-Authenticate": "Bearer"})
    audit_event("authentication", "success")
    return {"access_token": token, "token_type": "bearer", "expires_in": 1800}


@app.get("/api/customers", response_model=dict)
def customers(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, max_length=80),
    status: str | None = Query(None, pattern="^(verified|unverified)$"),
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
):
    statement = select(Customer)
    if status:
        statement = statement.where(Customer.verification_status == status)
    search_text = (search or "").strip()
    if search_text:
        escaped = search_text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        statement = statement.where(
            or_(
                Customer.customer_ref.ilike(pattern, escape="\\"),
                Customer.display_name.ilike(pattern, escape="\\"),
                Customer.phone_last4.ilike(pattern, escape="\\"),
            )
        )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(statement.order_by(Customer.created_at.desc()).limit(limit).offset(offset)).all()
    return {"items": [CustomerOut.model_validate(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@app.post("/api/customers/import", response_model=CustomerImportResult)
async def import_customers(file: UploadFile = File(...), db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        audit_event("customer_import", "rejected")
        raise HTTPException(status_code=422, detail="Upload a .csv file.")
    try:
        content = await file.read(MAX_IMPORT_BYTES + 1)
    finally:
        await file.close()
    if len(content) > MAX_IMPORT_BYTES:
        audit_event("customer_import", "rejected")
        raise HTTPException(status_code=413, detail="CSV file must be 2 MiB or smaller.")
    try:
        parsed = parse_customer_csv(content)
    except CsvFormatError as exc:
        audit_event("customer_import", "rejected")
        raise HTTPException(status_code=422, detail=str(exc)) from None

    inserted_refs: list[str] = []
    if parsed.rows:
        try:
            existing = set(db.scalars(select(Customer.customer_ref).where(
                Customer.customer_ref.in_([row.customer_ref for row in parsed.rows])
            )).all())
            for row in parsed.rows:
                if row.customer_ref in existing:
                    continue
                imported_customer = Customer(
                    id=uuid.uuid4(), customer_ref=row.customer_ref,
                    display_name=row.display_name, birth_year=row.birth_year,
                    phone_last4=row.phone_last4,
                    preferred_language=row.preferred_language,
                    do_not_call=row.do_not_call,
                    verification_status="unverified",
                )
                db.add(imported_customer)
                if row.do_not_call:
                    db.add(DoNotCallEvent(customer_id=imported_customer.id, action="requested", source="customer_import", actor=_admin))
                inserted_refs.append(row.customer_ref)
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            audit_event("customer_import", "failed")
            raise HTTPException(status_code=503, detail="Customer import could not be completed.") from None

    audit_event("customer_import", "completed", total=parsed.total_rows, imported=len(inserted_refs), duplicates=parsed.duplicate_rows + len(parsed.rows) - len(inserted_refs), rejected=parsed.rejected_rows)
    return CustomerImportResult(
        total_rows=parsed.total_rows,
        imported_rows=len(inserted_refs),
        duplicate_rows=parsed.duplicate_rows + len(parsed.rows) - len(inserted_refs),
        rejected_rows=parsed.rejected_rows,
        errors=parsed.errors[:MAX_RETURNED_ERRORS],
        errors_truncated=parsed.errors_truncated,
    )


@app.post("/api/customers/import/preview")
async def preview_customer_import(file: UploadFile = File(...), db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail="Upload a .csv file.")
    try:
        content = await file.read(MAX_IMPORT_BYTES + 1)
    finally:
        await file.close()
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="CSV file must be 2 MiB or smaller.")
    try:
        parsed = parse_customer_csv(content)
    except CsvFormatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    refs = [row.customer_ref for row in parsed.rows]
    existing = set(db.scalars(select(Customer.customer_ref).where(Customer.customer_ref.in_(refs))).all()) if refs else set()
    candidates = [row for row in parsed.rows if row.customer_ref not in existing]
    return {
        "total_rows": parsed.total_rows,
        "ready_rows": len(candidates),
        "duplicate_rows": parsed.duplicate_rows + len(existing),
        "rejected_rows": parsed.rejected_rows,
        "errors": parsed.errors[:MAX_RETURNED_ERRORS],
        "errors_truncated": parsed.errors_truncated,
        "preview_truncated": len(candidates) > 200,
        "preview": [{"row": row.row_number, "customer_ref": row.customer_ref, "display_name": row.display_name, "phone_last4": row.phone_last4} for row in candidates[:200]],
    }


@app.post("/api/customers", response_model=CustomerOut, status_code=201)
def create_customer(payload: CustomerWrite, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    customer = Customer(id=uuid.uuid4(), **payload.model_dump(), verification_status="unverified")
    db.add(customer)
    if customer.do_not_call:
        db.add(DoNotCallEvent(customer_id=customer.id, action="requested", source="customer_management", actor=_admin))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Customer reference already exists.") from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Customer could not be saved.") from None
    db.refresh(customer)
    audit_event("customer_record", "created", action="create")
    return customer


@app.patch("/api/customers/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: uuid.UUID, payload: CustomerWrite, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    if customer.do_not_call and "do_not_call" in payload.model_fields_set and payload.do_not_call is False:
        raise HTTPException(409, "A Do Not Call request can only be released through the documented release action.")
    was_dnc = customer.do_not_call
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(customer, key, value)
    if not was_dnc and customer.do_not_call:
        db.add(DoNotCallEvent(customer_id=customer.id, action="requested", source="customer_management", actor=_admin))
    customer.verification_status = "unverified"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Customer reference already exists.") from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Customer could not be saved.") from None
    db.refresh(customer)
    audit_event("customer_record", "updated", action="update")
    return customer


@app.get("/api/customers/{customer_id}/do-not-call-events")
def do_not_call_events(customer_id: uuid.UUID, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    if not db.get(Customer, customer_id):
        raise HTTPException(404, "Customer not found")
    rows = db.scalars(select(DoNotCallEvent).where(DoNotCallEvent.customer_id == customer_id).order_by(DoNotCallEvent.created_at.desc()).limit(100)).all()
    return [{"action": row.action, "source": row.source, "reason": row.reason, "created_at": row.created_at} for row in rows]


@app.post("/api/customers/{customer_id}/do-not-call/release", response_model=CustomerOut)
def release_do_not_call(customer_id: uuid.UUID, payload: DoNotCallRelease, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    if not customer.do_not_call:
        raise HTTPException(409, "Customer has no active Do Not Call restriction.")
    customer.do_not_call = False
    db.add(DoNotCallEvent(customer_id=customer.id, action="released", source="authorized_release", actor=_admin, reason=payload.reason.strip()))
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "Do Not Call release could not be recorded.") from None
    db.refresh(customer)
    audit_event("do_not_call", "released", action="authorized_release")
    return customer


@app.get("/api/customers/{customer_id}", response_model=CustomerOut)
def customer_detail(customer_id: uuid.UUID, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    row = db.get(Customer, customer_id)
    if not row:
        raise HTTPException(404, "Customer not found")
    return row


@app.get("/api/customers/{customer_id}/demo-verification-fixture")
def demo_verification_fixture(customer_id: uuid.UUID, request: Request, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    """Admin-only retrieval of fictional seed factors for evaluator demonstrations."""
    limit_request(request, "demo_fixture", settings.verification_rate_limit_per_minute)
    row = db.get(Customer, customer_id)
    if not row or not row.customer_ref.startswith("DEMO-") or not row.birth_year:
        raise HTTPException(404, "Fictional demo verification fixture not found.")
    audit_event("demo_verification_fixture", "retrieved")
    return {"customer_ref": row.customer_ref, "display_name": row.display_name, "birth_year": row.birth_year, "demo_only": True}


@app.get("/api/customers/{customer_id}/verification-history", response_model=list[VerificationEventOut])
def customer_verification_history(customer_id: uuid.UUID, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    if not db.get(Customer, customer_id):
        raise HTTPException(404, "Customer not found")
    return db.scalars(select(VerificationEvent).where(VerificationEvent.customer_id == customer_id).order_by(VerificationEvent.created_at.desc()).limit(100)).all()


@app.post(
    "/api/customers/{customer_id}/verify",
    response_model=CustomerVerificationResult,
)
def verify_customer(
    customer_id: uuid.UUID,
    payload: CustomerVerificationRequest,
    request: Request,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
):
    limit_request(request, "verification", settings.verification_rate_limit_per_minute)
    customer = db.scalar(select(Customer).where(Customer.id == customer_id))
    submitted_name = normalize_name_for_comparison(payload.display_name or "")
    submitted_year = unicodedata.normalize("NFKC", payload.birth_year or "").strip()
    valid_year = bool(re.fullmatch(r"[0-9]{4}", submitted_year))
    valid_year = valid_year and 1900 <= int(submitted_year) <= date.today().year
    expected_name = normalize_name_for_comparison(customer.display_name) if customer else "unknown customer"
    expected_year = f"{customer.birth_year:04d}" if customer and customer.birth_year else "0000"
    name_matches = hmac.compare_digest(expected_name.encode("utf-8"), submitted_name.encode("utf-8"))
    year_matches = hmac.compare_digest(expected_year.encode("ascii"), submitted_year.encode("utf-8"))
    verified = bool(
        customer
        and customer.birth_year
        and submitted_name
        and valid_year
        and name_matches
        and year_matches
    )

    if verified:
        customer.verification_status = "verified"
        db.add(VerificationEvent(verified=True, customer_id=customer.id))
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            raise HTTPException(status_code=503, detail="Verification is temporarily unavailable.") from None
        audit_event("identity_verification", "success")
        return CustomerVerificationResult(verified=True, message="Customer verified.")
    db.add(VerificationEvent(verified=False, customer_id=customer.id if customer else None))
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Verification is temporarily unavailable.") from None
    audit_event("identity_verification", "failure")
    return CustomerVerificationResult(verified=False, message="Unable to verify customer.")


@app.get("/api/calls", response_model=dict)
def calls(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), outcome: CallOutcome | None = None, customer_ref: str | None = Query(None, max_length=64), verification_status: str | None = Query(None, pattern="^(verified|unverified)$"), date_from: date | None = None, date_to: date | None = None, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    statement = select(Call)
    if customer_ref or verification_status:
        statement = statement.join(Customer)
    if outcome:
        statement = statement.where(Call.outcome == outcome)
    if customer_ref:
        statement = statement.where(Customer.customer_ref.ilike(customer_ref))
    if verification_status:
        statement = statement.where(Customer.verification_status == verification_status)
    if date_from:
        statement = statement.where(Call.started_at >= _local_day_bound(date_from))
    if date_to:
        statement = statement.where(Call.started_at <= _local_day_bound(date_to, end=True))
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must be on or before date_to.")
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(statement.order_by(Call.started_at.desc()).limit(limit).offset(offset)).all()
    return {"items": [serialize_call(row) for row in rows], "total": total, "limit": limit, "offset": offset}


def serialize_call(row: Call) -> CallOut:
    customer = row.customer
    def not_expired(value: datetime) -> bool:
        normalized = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return normalized > datetime.now(timezone.utc)
    values = CallOut(
        id=row.id, customer_id=row.customer_id, status=row.status, outcome=row.outcome,
        direction=row.direction, started_at=row.started_at, ended_at=row.ended_at,
        callback_requested=row.callback_requested, simulated=bool(row.simulated),
        channel=row.channel or ("scripted_simulation" if row.simulated else "operational_record"),
        voice_state=row.voice_state or "new", verification_attempts=row.verification_attempts or 0,
        voice_verified=bool(row.voice_verified),
    ).model_dump()
    allowed_provenance = "browser_voice" if row.channel == "browser_voice" else "local_simulation"
    transcript_allowed = row.simulated and any(item.provenance == allowed_provenance for item in row.transcript)
    values.update(
        customer_ref=customer.customer_ref if customer else None,
        customer_display_name=customer.display_name if customer else None,
        verification_status=customer.verification_status if customer else None,
        duration_seconds=max(0, int((row.ended_at - row.started_at).total_seconds())) if row.ended_at else None,
        transcript_available=bool(row.transcript) and (not row.simulated or transcript_allowed) and any(not_expired(item.expires_at) for item in row.transcript),
        summary=row.summary_record.content if row.summary_record and row.summary_record.status == "completed" and not_expired(row.summary_record.expires_at) else None,
        callback_status=next((item.status for item in row.callbacks if item.status in {"pending", "scheduled"}), None),
    )
    return CallOut.model_validate(values)


@app.post("/api/calls", response_model=CallOut, status_code=201)
def create_call(payload: CallCreate, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    if payload.direction == "outbound" and not settings.outbound_calling_enabled:
        raise HTTPException(409, "Outbound call workflows are disabled.")
    customer = db.get(Customer, payload.customer_id) if payload.customer_id else None
    if payload.customer_id and not customer:
        raise HTTPException(404, "Customer not found")
    if payload.direction == "outbound":
        if not customer or not customer.outbound_consent_at or not customer.consent_source or customer.do_not_call:
            raise HTTPException(403, "Customer is not eligible for an outbound workflow.")
        if not calling_window_open(utc_now(), settings.calling_timezone, settings.calling_hour_start, settings.calling_hour_end):
            raise HTTPException(403, "Outbound workflows are outside the configured calling window.")
    call = Call(**payload.model_dump(), simulated=True)
    db.add(call)
    db.flush()
    db.add(CallLifecycleEvent(call_id=call.id, event_type="record_created", status=call.status.value))
    db.commit()
    db.refresh(call)
    audit_event("call_record", "created", action="create")
    return serialize_call(call)


def _save_demo_call(db: Session, customer: Customer, persona: str) -> Call:
    """Run one deterministic local persona; this path never contacts telephony."""
    if customer.do_not_call and persona != "do_not_call":
        raise HTTPException(403, "This customer has a Do Not Call restriction.")
    if customer.do_not_call and persona == "do_not_call":
        raise HTTPException(403, "This customer already has a Do Not Call restriction.")
    if not customer.birth_year and persona in {"right_customer_hindi", "wrong_birth_year_english"}:
        raise HTTPException(409, "A birth year is required for this verification demo.")
    now = datetime.now(timezone.utc)
    result = run_persona(customer, persona, now, settings.calling_timezone)
    call = Call(
        customer_id=customer.id,
        status=CallStatus.completed if result.connected else CallStatus.failed,
        outcome=result.outcome,
        direction="outbound",
        started_at=now,
        ended_at=now + timedelta(seconds=result.simulated_seconds),
        simulated=True,
        language=result.language,
        callback_requested=result.outcome == CallOutcome.callback_requested,
    )
    db.add(call)
    db.flush()
    db.add(CallLifecycleEvent(call_id=call.id, event_type="simulation_started", status="queued"))
    if result.connected:
        db.add(CallLifecycleEvent(call_id=call.id, event_type="simulation_connected", status="connected"))
    if result.messages:
        persist_transcript(db, call, list(result.messages), "local_simulation", result.language)
        persist_summary(
            db, call,
            three_line_summary(result.outcome, result.connected, result.callback_at, settings.calling_timezone),
            "local_simulation",
        )
    if result.outcome:
        record_call_outcome(
            db, call, result.outcome, scheduled_at=result.callback_at,
            timezone_name=settings.calling_timezone if result.callback_at else None,
            reason="Third party requested a callback" if persona == "third_party_callback" else "Respondent requested a callback",
        )
    if result.outcome in {CallOutcome.right_customer, CallOutcome.verification_failed}:
        db.add(VerificationEvent(verified=result.outcome == CallOutcome.right_customer, simulated=True, customer_id=customer.id, call_id=call.id))
    if result.do_not_call:
        customer.do_not_call = True
        db.add(DoNotCallEvent(customer_id=customer.id, action="requested", source="simulated_persona", actor="system"))
        db.add(CallLifecycleEvent(call_id=call.id, event_type="do_not_call_requested", status="completed"))
    db.add(CallLifecycleEvent(call_id=call.id, event_type="simulation_completed", status=call.status.value))
    return call


@app.post("/api/voice-sessions", status_code=201)
def create_voice_session(payload: VoiceSessionCreate, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    if settings.app_env not in {"development", "test"}:
        raise HTTPException(403, "Browser voice simulation is disabled outside development.")
    customer = db.get(Customer, payload.customer_id)
    if not customer or not customer.customer_ref.startswith("DEMO-"):
        raise HTTPException(404, "Choose a fictional demo customer.")
    if customer.do_not_call:
        raise HTTPException(403, "This customer has an active Do Not Call restriction.")
    call = Call(customer_id=customer.id, direction="inbound", status=CallStatus.connected, simulated=True,
                channel="browser_voice", language=payload.language, voice_state="active")
    db.add(call)
    db.flush()
    engine = ConversationEngine()
    greeting = engine.start(payload.language, simulated=True).message
    call.started_at = datetime.now(timezone.utc)
    db.add(TranscriptMessage(call_id=call.id, speaker="assistant", content=greeting,
        provenance="browser_voice", language=payload.language,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.transcript_retention_days)))
    db.add(CallLifecycleEvent(call_id=call.id, event_type="browser_voice_started", status="connected"))
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "The voice session could not be saved.") from None
    return {"call_id": str(call.id), "greeting": greeting, "language": payload.language, "simulated": True}


@app.post("/api/voice-sessions/{call_id}/turn")
def voice_session_turn(call_id: uuid.UUID, payload: VoiceTurnInput, request: Request,
                       db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    limit_request(request, "voice_turn", settings.auth_rate_limit_per_minute * 3)
    call = db.get(Call, call_id)
    if not call or not call.simulated or call.channel != "browser_voice":
        raise HTTPException(404, "Browser voice session not found.")
    prior = db.scalar(select(VoiceTurnRequest).where(
        VoiceTurnRequest.call_id == call.id, VoiceTurnRequest.turn_id == payload.turn_id,
    ))
    if prior:
        return {"response": prior.response, "language": prior.language, "state": prior.state,
                "outcome": prior.outcome, "ended": prior.ended,
                "verification_attempts": prior.verification_attempts}
    if call.status != CallStatus.connected or call.voice_state in {"ended", "handoff"}:
        raise HTTPException(409, "This voice session has ended.")
    if call.customer and call.customer.do_not_call:
        raise HTTPException(403, "This customer has an active Do Not Call restriction.")
    customer = call.customer
    def verify(name: str, year: str) -> bool:
        name_match, year_match = verify_factors(name, year)
        return bool(name_match and year_match)
    def verify_factors(name: str | None, year: str | None) -> tuple[bool | None, bool | None]:
        if not customer:
            return (False if name is not None else None, False if year is not None else None)
        name_match: bool | None = None
        year_match: bool | None = None
        if name is not None:
            actual_name = normalize_name_for_comparison(name)
            expected_name = normalize_name_for_comparison(customer.display_name)
            name_match = bool(actual_name and hmac.compare_digest(actual_name.encode("utf-8"), expected_name.encode("utf-8")))
        if year is not None:
            normalized_year = unicodedata.normalize("NFKC", year).translate(str.maketrans("\u0966\u0967\u0968\u0969\u096a\u096b\u096c\u096d\u096e\u096f", "0123456789"))
            expected_year = str(customer.birth_year or "0000")
            year_match = bool(customer.birth_year and hmac.compare_digest(normalized_year.encode("ascii"), expected_year.encode("ascii")))
        return name_match, year_match
    was_verifying = call.voice_state == "verifying"
    was_callback_offered = call.voice_state == "callback_offered"
    _, _, has_verification_factors = extract_verification_factors(payload.text.strip(), allow_bare_name=was_verifying)
    engine = ConversationEngine(
        verify,
        factor_verifier=verify_factors,
        pending_name_verified=call.verification_name_match,
        pending_year_verified=call.verification_year_match,
        verification_attempts=call.verification_attempts,
    )
    engine.state = ConversationState(call.voice_state)
    engine.language = payload.language
    engine.identity_verified = call.voice_verified
    attempts_before = engine.verification_attempts
    response = engine.handle(payload.text.strip())
    if response.intent == "general_enquiry" and not response.ended:
        model_reply = safe_small_talk(payload.text.strip(), response.language, settings)
        if model_reply:
            response = response.__class__(message=model_reply, state=response.state, language=response.language, intent=response.intent)
    call.language = response.language
    call.voice_state = response.state.value
    call.verification_attempts = engine.verification_attempts
    call.verification_name_match = engine.pending_name_verified
    call.verification_year_match = engine.pending_year_verified
    if response.outcome:
        call.status = CallStatus.completed
        call.ended_at = datetime.now(timezone.utc)
        if response.outcome == CallOutcome.callback_requested:
            scheduled_at = parse_requested_callback_time(payload.text, settings.calling_timezone)
            record_call_outcome(
                db, call, response.outcome, scheduled_at=scheduled_at,
                timezone_name=settings.calling_timezone,
                reason="Third party suggested a callback" if was_callback_offered else "Respondent requested a callback",
            )
        else:
            record_call_outcome(db, call, response.outcome)
    if response.outcome == CallOutcome.right_customer:
        call.voice_verified = True
    if any(event.kind == "do_not_call_requested" for event in response.events) and customer:
        customer.do_not_call = True
        db.add(DoNotCallEvent(customer_id=customer.id, action="requested", source="browser_voice", actor=_admin))
    if engine.verification_attempts > attempts_before:
        verified = engine.identity_verified
        db.add(VerificationEvent(verified=verified, simulated=True, customer_id=customer.id if customer else None, call_id=call.id))
    redacted = "[verification response redacted]" if was_verifying or has_verification_factors else payload.text.strip()
    now = datetime.now(timezone.utc)
    db.add(TranscriptMessage(call_id=call.id, speaker="customer", content=redacted,
        provenance="browser_voice", language=payload.language,
        expires_at=now + timedelta(days=settings.transcript_retention_days)))
    db.add(TranscriptMessage(call_id=call.id, speaker="assistant", content=response.message,
        provenance="browser_voice", language=response.language,
        created_at=now + timedelta(microseconds=1),
        expires_at=now + timedelta(days=settings.transcript_retention_days)))
    saved_turn = VoiceTurnRequest(call_id=call.id, turn_id=payload.turn_id, response=response.message,
        language=response.language, state=response.state.value,
        outcome=response.outcome.value if response.outcome else None, ended=response.ended,
        verification_attempts=call.verification_attempts)
    db.add(saved_turn)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = db.scalar(select(VoiceTurnRequest).where(
            VoiceTurnRequest.call_id == call_id, VoiceTurnRequest.turn_id == payload.turn_id,
        ))
        if prior:
            return {"response": prior.response, "language": prior.language, "state": prior.state,
                    "outcome": prior.outcome, "ended": prior.ended,
                    "verification_attempts": prior.verification_attempts}
        raise HTTPException(503, "The voice turn could not be saved.") from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "The voice turn could not be saved.") from None
    return {"response": response.message, "language": response.language, "state": response.state.value,
            "outcome": response.outcome.value if response.outcome else None, "ended": response.ended,
            "verification_attempts": call.verification_attempts}


@app.post("/api/voice-sessions/{call_id}/metrics", status_code=201)
def save_voice_metric(call_id: uuid.UUID, payload: VoiceMetricInput, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    call = db.get(Call, call_id)
    if not call or not call.simulated or call.channel != "browser_voice":
        raise HTTPException(404, "Browser voice session not found.")
    stamps = [payload.utterance_ended_at, payload.recognition_completed_at, payload.request_started_at, payload.response_received_at, payload.speech_started_at]
    millis = [int(value.timestamp() * 1000) for value in stamps]
    if any(later < earlier for earlier, later in zip(millis, millis[1:])) or millis[-1] - millis[0] > 120_000:
        raise HTTPException(422, "Voice timing samples must be ordered and no more than two minutes apart.")
    metric = VoiceTurnMetric(call_id=call.id, turn_id=payload.turn_id,
        utterance_ended_at=stamps[0], recognition_completed_at=stamps[1], request_started_at=stamps[2],
        response_received_at=stamps[3], speech_started_at=stamps[4],
        response_latency_ms=millis[4]-millis[0], recognition_latency_ms=millis[1]-millis[0],
        server_processing_ms=millis[3]-millis[2], synthesis_start_latency_ms=millis[4]-millis[3])
    db.add(metric)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This voice timing sample was already saved.") from None
    return {"response_latency_ms": metric.response_latency_ms, "recognition_latency_ms": metric.recognition_latency_ms,
            "server_processing_ms": metric.server_processing_ms, "synthesis_start_latency_ms": metric.synthesis_start_latency_ms}


@app.post("/api/voice-sessions/{call_id}/end")
def end_voice_session(call_id: uuid.UUID, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    call = db.get(Call, call_id)
    if not call or not call.simulated or call.channel != "browser_voice":
        raise HTTPException(404, "Browser voice session not found.")
    if call.status == CallStatus.connected:
        has_customer_turn = db.scalar(select(TranscriptMessage.id).where(TranscriptMessage.call_id == call.id, TranscriptMessage.speaker == "customer").limit(1))
        call.status = CallStatus.completed
        call.ended_at = datetime.now(timezone.utc)
        if not call.outcome:
            if has_customer_turn or (call.customer and call.customer.do_not_call):
                call.status = CallStatus.disconnected
            else:
                record_call_outcome(db, call, CallOutcome.not_connected)
    else:
        has_customer_turn = db.scalar(select(TranscriptMessage.id).where(TranscriptMessage.call_id == call.id, TranscriptMessage.speaker == "customer").limit(1))
    existing_summary = db.scalar(select(CallSummary.id).where(CallSummary.call_id == call.id))
    if has_customer_turn and not existing_summary:
            outcome_label = "Do Not Call request recorded" if call.customer and call.customer.do_not_call else (call.outcome.value.replace("_", " ").title() if call.outcome else "Session ended by operator")
            verification_label = "Identity verification passed." if call.voice_verified else ("Identity verification attempted; protected details were not disclosed." if call.verification_attempts else "Identity verification was not attempted.")
            summary = f"A respondent participated in a browser voice simulation; recognized text was stored and audio was not.\n{verification_label}\nFinal outcome: {outcome_label}."
            persist_summary(db, call, summary, "browser_voice")
    if call.status != CallStatus.connected:
        call.voice_state = "ended"
        db.add(CallLifecycleEvent(call_id=call.id, event_type="browser_voice_ended", status="completed"))
        db.commit()
    return {"call_id": str(call.id), "status": call.status.value, "outcome": call.outcome.value if call.outcome else None}


@app.post("/api/demo/persona/{persona}")
def run_demo_persona(persona: str, customer_id: uuid.UUID = Query(...), db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    if settings.app_env not in {"development", "test"}:
        raise HTTPException(403, "The local persona simulator is disabled outside development.")
    if persona not in DEMO_PERSONAS:
        raise HTTPException(422, "Choose one of the documented demo personas.")
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    if not customer.customer_ref.startswith("DEMO-"):
        raise HTTPException(403, "The persona simulator only accepts fictional DEMO- customers.")
    call = _save_demo_call(db, customer, persona)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "The simulated call could not be saved.") from None
    db.refresh(call)
    audit_event("simulated_call", "completed", persona=persona)
    if persona == "do_not_call":
        audit_event("do_not_call", "recorded", action="opt_out")
    return serialize_call(call)


@app.post("/api/demo/run-suite")
def run_demo_suite(db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    if settings.app_env not in {"development", "test"}:
        raise HTTPException(403, "The local persona simulator is disabled outside development.")
    customers = db.scalars(select(Customer).where(Customer.customer_ref.like("DEMO-%"), Customer.do_not_call == false(), Customer.birth_year.is_not(None)).order_by(Customer.customer_ref).limit(6)).all()
    if len(customers) < 6:
        raise HTTPException(409, "Import at least six eligible fictional customers before running the outcome suite.")
    created: list[Call] = []
    try:
        for _run in range(2):
            for customer, persona in zip(customers, SUITE_PERSONAS, strict=True):
                created.append(_save_demo_call(db, customer, persona))
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "The persona suite could not be saved atomically.") from None
    audit_event("simulated_persona_suite", "completed", calls=len(created))
    return {"created": len(created), "calls": [serialize_call(call) for call in created]}


@app.get("/api/calls/{call_id}", response_model=CallOut)
def call_detail(call_id: uuid.UUID, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    row = db.get(Call, call_id)
    if not row:
        raise HTTPException(404, "Call not found")
    return serialize_call(row)


@app.get("/api/calls/{call_id}/events", response_model=list[CallLifecycleEventOut])
def call_lifecycle_events(call_id: uuid.UUID, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    if not db.get(Call, call_id):
        raise HTTPException(404, "Call not found")
    return db.scalars(
        select(CallLifecycleEvent).where(CallLifecycleEvent.call_id == call_id).order_by(CallLifecycleEvent.created_at)
    ).all()


@app.patch("/api/calls/{call_id}/status", response_model=CallOut)
def update_call_status(call_id: uuid.UUID, payload: CallLifecycleUpdate, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    row = db.get(Call, call_id)
    if not row:
        raise HTTPException(404, "Call not found")
    if row.status not in {CallStatus.queued, CallStatus.connected}:
        raise HTTPException(409, "Only queued or connected call records can transition to a terminal status.")
    row.status = CallStatus(payload.status)
    row.ended_at = datetime.now(timezone.utc)
    db.add(CallLifecycleEvent(call_id=row.id, event_type="status_changed", status=row.status.value))
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "Call status could not be saved.") from None
    db.refresh(row)
    audit_event("call_lifecycle", payload.status, action="status_change")
    return serialize_call(row)


@app.get("/api/calls/{call_id}/transcript")
def call_transcript(call_id: uuid.UUID, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(404, "Call not found")
    messages = db.scalars(select(TranscriptMessage).where(TranscriptMessage.call_id == call_id, TranscriptMessage.expires_at > datetime.now(timezone.utc)).order_by(TranscriptMessage.created_at)).all()
    if call.simulated:
        allowed = "browser_voice" if call.channel == "browser_voice" else "local_simulation"
        messages = [message for message in messages if message.provenance == allowed]
    return {"available": bool(messages), "simulated": call.simulated, "messages": [TranscriptMessageOut.model_validate(item) for item in messages]}


@app.get("/api/calls/{call_id}/summary", response_model=CallSummaryOut)
def call_summary(call_id: uuid.UUID, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(404, "Call not found")
    if call.simulated and not db.scalar(select(TranscriptMessage.id).where(TranscriptMessage.call_id == call_id, TranscriptMessage.provenance == ("browser_voice" if call.channel == "browser_voice" else "local_simulation")).limit(1)):
        return CallSummaryOut(status="unavailable")
    summary = db.scalar(select(CallSummary).where(CallSummary.call_id == call_id, CallSummary.expires_at > datetime.now(timezone.utc)))
    return CallSummaryOut.model_validate(summary) if summary else CallSummaryOut(status="unavailable")


@app.post("/api/calls/{call_id}/summary/retry", response_model=CallSummaryOut)
def retry_call_summary(call_id: uuid.UUID, request: Request, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    limit_request(request, "summary", settings.auth_rate_limit_per_minute)
    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(404, "Call not found")
    if call.simulated:
        raise HTTPException(409, "Summaries are unavailable for simulated calls.")
    has_transcript = db.scalar(select(TranscriptMessage.id).where(TranscriptMessage.call_id == call_id).limit(1))
    if not has_transcript:
        raise HTTPException(409, "A transcript is required before summary generation.")
    summary = db.scalar(select(CallSummary).where(CallSummary.call_id == call_id))
    if summary and summary.expires_at <= datetime.now(timezone.utc):
        summary.status = "failed"
        summary.content = None
        summary.provenance = None
        summary.error_code = None
    if summary and summary.status == "completed":
        raise HTTPException(409, "A completed summary cannot be retried.")
    if summary is None:
        summary = CallSummary(id=uuid.uuid4(), call_id=call_id, status="failed", attempts=0)
        db.add(summary)
    summary.status = "failed"
    summary.attempts += 1
    summary.error_code = "provider_unconfigured"
    db.commit()
    db.refresh(summary)
    audit_event("call_summary_retry", "provider_unconfigured", action="retry")
    return summary


@app.patch("/api/calls/{call_id}/outcome", response_model=CallOut)
def update_call_outcome(call_id: uuid.UUID, payload: CallOutcomeUpdate, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    row = db.get(Call, call_id)
    if not row:
        raise HTTPException(404, "Call not found")
    if row.outcome is not None and row.outcome != payload.outcome:
        raise HTTPException(409, "A finalized call outcome cannot be replaced.")
    record_call_outcome(db, row, payload.outcome)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An active callback follow-up already exists for this call.") from None
    db.refresh(row)
    audit_event("call_record", "updated", action="outcome_update")
    return serialize_call(row)


@app.get("/api/calls/{call_id}/callbacks", response_model=list[CallbackOut])
def call_callbacks(call_id: uuid.UUID, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    if not db.get(Call, call_id):
        raise HTTPException(404, "Call not found")
    return db.scalars(select(CallbackFollowUp).where(CallbackFollowUp.call_id == call_id).order_by(CallbackFollowUp.created_at.desc())).all()


@app.post("/api/calls/{call_id}/callbacks", response_model=CallbackOut, status_code=201)
def create_callback(call_id: uuid.UUID, payload: CallbackCreate, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(404, "Call not found")
    if not call.callback_requested:
        raise HTTPException(409, "A callback can only be scheduled for a callback request outcome.")
    active = db.scalar(select(CallbackFollowUp.id).where(CallbackFollowUp.call_id == call.id, CallbackFollowUp.status.in_(["pending", "scheduled"])))
    if active:
        raise HTTPException(409, "An active callback follow-up already exists for this call.")
    status = "scheduled" if payload.scheduled_at else "pending"
    followup = CallbackFollowUp(id=uuid.uuid4(), call_id=call.id, status=status, scheduled_at=payload.scheduled_at,
        timezone_name=payload.timezone_name or settings.calling_timezone, reason=payload.reason or "Operator scheduled callback", notes=payload.notes)
    db.add(followup)
    db.add(CallbackFollowUpEvent(followup_id=followup.id, status=status))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An active callback follow-up already exists for this call.") from None
    db.refresh(followup)
    audit_event("callback_followup", "created", action="create")
    return followup


@app.patch("/api/callbacks/{callback_id}", response_model=CallbackOut)
def update_callback(callback_id: uuid.UUID, payload: CallbackUpdate, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    followup = db.get(CallbackFollowUp, callback_id)
    if not followup:
        raise HTTPException(404, "Callback follow-up not found")
    if followup.status not in {"pending", "scheduled"}:
        raise HTTPException(409, "This callback follow-up is already closed.")
    followup.status = payload.status
    if payload.scheduled_at is not None:
        followup.scheduled_at = payload.scheduled_at
        followup.timezone_name = payload.timezone_name or settings.calling_timezone
    if payload.reason is not None:
        followup.reason = payload.reason
    if "notes" in payload.model_fields_set:
        followup.notes = payload.notes
    db.add(CallbackFollowUpEvent(followup_id=followup.id, status=followup.status))
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "Callback follow-up could not be saved.") from None
    db.refresh(followup)
    audit_event("callback_followup", "updated", action="update")
    return followup


@app.get("/api/analytics/overview")
def analytics(db: Session = Depends(get_db), _admin: str = Depends(require_admin)) -> dict[str, int]:
    return {
        "total_calls": db.scalar(select(func.count()).select_from(Call)) or 0,
        "verified_customers": db.scalar(select(func.count()).select_from(Customer).where(Customer.verification_status == "verified")) or 0,
        "callback_requests": db.scalar(select(func.count()).select_from(Call).where(Call.callback_requested == true())) or 0,
        "failed_calls": db.scalar(select(func.count()).select_from(Call).where(Call.status.in_([CallStatus.failed, CallStatus.disconnected]))) or 0,
    }


@app.get("/api/analytics/dashboard")
def dashboard_analytics(db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    """Dashboard summaries derived from persisted records; no sample metrics."""
    counts = {outcome.value: db.scalar(select(func.count()).select_from(Call).where(Call.outcome == outcome)) or 0 for outcome in CallOutcome}
    call_day = func.date(Call.started_at) if db.get_bind().dialect.name == "sqlite" else cast(Call.started_at, Date)
    days = db.execute(select(call_day.label("day"), func.count().label("count")).group_by(call_day).order_by(call_day.desc()).limit(14)).all()
    return {
        "total_customers": db.scalar(select(func.count()).select_from(Customer)) or 0,
        "total_calls": db.scalar(select(func.count()).select_from(Call)) or 0,
        "successful_verifications": db.scalar(select(func.count()).select_from(VerificationEvent).where(VerificationEvent.verified == true())) or 0,
        "successful_customer_contacts": counts[CallOutcome.right_customer.value],
        "do_not_call_customers": db.scalar(select(func.count()).select_from(Customer).where(Customer.do_not_call == true())) or 0,
        "verification_events_successful": db.scalar(select(func.count()).select_from(VerificationEvent).where(VerificationEvent.verified == true())) or 0,
        "verification_events_failed": db.scalar(select(func.count()).select_from(VerificationEvent).where(VerificationEvent.verified == false())) or 0,
        "callbacks_requested": db.scalar(select(func.count()).select_from(Call).where(Call.callback_requested == true())) or 0,
        "callbacks_pending": db.scalar(select(func.count()).select_from(CallbackFollowUp).where(CallbackFollowUp.status == "pending")) or 0,
        "callbacks_scheduled": db.scalar(select(func.count()).select_from(CallbackFollowUp).where(CallbackFollowUp.status == "scheduled")) or 0,
        "callbacks_completed": db.scalar(select(func.count()).select_from(CallbackFollowUp).where(CallbackFollowUp.status == "completed")) or 0,
        "failed_connections": db.scalar(select(func.count()).select_from(Call).where(Call.status.in_([CallStatus.failed, CallStatus.disconnected]))) or 0,
        "outcomes": counts,
        "activity": [{"date": day.isoformat() if hasattr(day, "isoformat") else str(day), "calls": count} for day, count in reversed(days)],
        "voice_latency_samples": db.scalar(select(func.count()).select_from(VoiceTurnMetric)) or 0,
        "average_voice_response_latency_ms": db.scalar(select(func.avg(VoiceTurnMetric.response_latency_ms))) if db.scalar(select(func.count()).select_from(VoiceTurnMetric)) else None,
    }


@app.get("/api/reports/calls")
def call_report(date_from: date | None = None, date_to: date | None = None, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must be on or before date_to.")
    call_filters = []
    verify_filters = []
    callback_filters = []
    if date_from:
        call_filters.append(Call.started_at >= _local_day_bound(date_from))
        verify_filters.append(VerificationEvent.created_at >= _local_day_bound(date_from))
        callback_filters.append(CallbackFollowUp.created_at >= _local_day_bound(date_from))
    if date_to:
        call_filters.append(Call.started_at <= _local_day_bound(date_to, end=True))
        verify_filters.append(VerificationEvent.created_at <= _local_day_bound(date_to, end=True))
        callback_filters.append(CallbackFollowUp.created_at <= _local_day_bound(date_to, end=True))
    outcomes = {outcome.value: db.scalar(select(func.count()).select_from(Call).where(*call_filters, Call.outcome == outcome)) or 0 for outcome in CallOutcome}
    call_day = func.date(Call.started_at) if db.get_bind().dialect.name == "sqlite" else cast(Call.started_at, Date)
    daily_rows = db.execute(select(call_day, func.count()).where(*call_filters).group_by(call_day).order_by(call_day)).all()
    total_calls = db.scalar(select(func.count()).select_from(Call).where(*call_filters)) or 0
    connection_events = select(CallLifecycleEvent.call_id).where(CallLifecycleEvent.status == "connected").distinct()
    contact_outcomes = [CallOutcome.right_customer, CallOutcome.wrong_number, CallOutcome.third_party_answered, CallOutcome.callback_requested, CallOutcome.verification_failed]
    connected_calls = db.scalar(select(func.count()).select_from(Call).where(
        *call_filters,
        or_(Call.outcome.in_(contact_outcomes), Call.id.in_(connection_events)),
    )) or 0
    report_rates = call_rates(total_calls, connected_calls, outcomes[CallOutcome.right_customer.value])
    return {
        "total_calls": total_calls,
        "connected_calls": connected_calls,
        "not_connected_calls": max(0, total_calls - connected_calls),
        **report_rates,
        "outcomes": outcomes,
        "verification_successes": db.scalar(select(func.count()).select_from(VerificationEvent).where(*verify_filters, VerificationEvent.verified == true())) or 0,
        "verification_failures": db.scalar(select(func.count()).select_from(VerificationEvent).where(*verify_filters, VerificationEvent.verified == false())) or 0,
        "voice_latency_samples": db.scalar(select(func.count()).select_from(VoiceTurnMetric).join(Call, Call.id == VoiceTurnMetric.call_id).where(*call_filters)) or 0,
        "average_voice_response_latency_ms": db.scalar(select(func.avg(VoiceTurnMetric.response_latency_ms)).join(Call, Call.id == VoiceTurnMetric.call_id).where(*call_filters)),
        "callbacks_requested": db.scalar(select(func.count()).select_from(Call).where(*call_filters, Call.callback_requested == true())) or 0,
        "callbacks_pending": db.scalar(select(func.count()).select_from(CallbackFollowUp).where(*callback_filters, CallbackFollowUp.status == "pending")) or 0,
        "callbacks_scheduled": db.scalar(select(func.count()).select_from(CallbackFollowUp).where(*callback_filters, CallbackFollowUp.status == "scheduled")) or 0,
        "callbacks_completed": db.scalar(select(func.count()).select_from(CallbackFollowUp).where(*callback_filters, CallbackFollowUp.status == "completed")) or 0,
        "callbacks_missed": db.scalar(select(func.count()).select_from(CallbackFollowUp).where(*callback_filters, CallbackFollowUp.status == "missed")) or 0,
        "daily_activity": [{"date": day.isoformat() if hasattr(day, "isoformat") else str(day), "calls": count} for day, count in daily_rows],
    }


@app.get("/api/reports/calls.csv")
def export_call_report(date_from: date | None = None, date_to: date | None = None, db: Session = Depends(get_db), _admin: str = Depends(require_admin)):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must be on or before date_to.")
    statement = select(Call).order_by(Call.started_at.desc()).limit(10_000)
    if date_from:
        statement = statement.where(Call.started_at >= _local_day_bound(date_from))
    if date_to:
        statement = statement.where(Call.started_at <= _local_day_bound(date_to, end=True))
    rows = db.scalars(statement).all()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["call_id", "customer_reference", "direction", "status", "outcome", "started_at", "ended_at", "duration_seconds", "callback_requested"])
    for row in rows:
        writer.writerow([str(row.id), row.customer.customer_ref if row.customer else "", row.direction, row.status.value, row.outcome.value if row.outcome else "", row.started_at.isoformat(), row.ended_at.isoformat() if row.ended_at else "", max(0, int((row.ended_at - row.started_at).total_seconds())) if row.ended_at else "", row.callback_requested])
    output.seek(0)
    audit_event("call_report_export", "completed", total=len(rows))
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=shaha-call-report.csv"})

