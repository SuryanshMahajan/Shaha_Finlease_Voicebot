"""Signed Twilio Voice webhook and Conversation Relay WebSocket adapter."""
import asyncio
import hmac
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from sqlalchemy import false, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.config import get_settings
from app.core.security import audit_event
from app.db.session import SessionLocal
from app.models import Call, CallLifecycleEvent, CallOutcome, CallStatus
from app.services.call_records import record_call_outcome
from app.services.twilio_relay import (
    MAX_FRAME_BYTES,
    RelayProtocolError,
    TwilioRelaySession,
    build_completion_twiml,
    build_voice_twiml,
    canonical_webhook_url,
    canonical_websocket_url,
    integration_configured,
    validate_setup_message,
    validate_twilio_signature,
)

router = APIRouter(prefix="/api/twilio", tags=["Twilio Conversation Relay"])
_CALL_SID = re.compile(r"^CA[0-9a-fA-F]{32}$")
_active_call_sids: set[str] = set()


def relay_status() -> dict[str, Any]:
    settings = get_settings()
    configured = integration_configured(
        settings.twilio_account_sid,
        settings.twilio_auth_token,
        settings.twilio_public_base_url,
    )
    return {
        "name": "twilio_conversation_relay",
        "configured": configured,
        "mode": "conversation_relay" if configured else "unconfigured",
        "state": "connected" if configured and _active_call_sids else "configured" if configured else "unconfigured",
        "active_sessions": len(_active_call_sids),
    }


def _configured_or_raise() -> None:
    settings = get_settings()
    if not integration_configured(settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_public_base_url):
        raise HTTPException(status_code=503, detail="Twilio Conversation Relay is not configured on the backend.")


def _signature_valid(url: str, params: Any, signature: str | None) -> bool:
    settings = get_settings()
    return validate_twilio_signature(
        settings.twilio_auth_token,
        url,
        params,
        signature,
    )


async def _verified_form(request: Request) -> Any:
    _configured_or_raise()
    if request.url.query:
        raise HTTPException(status_code=403, detail="Twilio request rejected.")
    settings = get_settings()
    form = await request.form()
    url = canonical_webhook_url(settings.twilio_public_base_url, request.url.path)
    if not _signature_valid(url, form, request.headers.get("x-twilio-signature")):
        audit_event("twilio_webhook", "signature_rejected")
        raise HTTPException(status_code=403, detail="Twilio request rejected.")
    account_sid = str(form.get("AccountSid", ""))
    if not hmac.compare_digest(account_sid, settings.twilio_account_sid):
        audit_event("twilio_webhook", "account_rejected")
        raise HTTPException(status_code=403, detail="Twilio request rejected.")
    return form


def _xml(content: str) -> Response:
    return Response(content=content, media_type="application/xml; charset=utf-8")


async def _receive_relay_frame(websocket: WebSocket, timeout_seconds: float) -> str:
    return await asyncio.wait_for(websocket.receive_text(), timeout=timeout_seconds)


@router.post("/voice")
async def voice_webhook(request: Request) -> Response:
    """Signed inbound Voice webhook. It creates no outbound call and stores no phone number."""
    form = await _verified_form(request)
    call_sid = str(form.get("CallSid", ""))
    direction = str(form.get("Direction", "")).casefold()
    if not _CALL_SID.fullmatch(call_sid) or direction != "inbound":
        raise HTTPException(status_code=422, detail="A valid inbound Twilio call is required.")

    db = SessionLocal()
    try:
        call = db.scalar(select(Call).where(Call.provider_call_sid == call_sid))
        if call is None:
            call = Call(direction="inbound", status=CallStatus.queued, simulated=False, provider_call_sid=call_sid)
            db.add(call)
            db.flush()
            db.add(CallLifecycleEvent(call_id=call.id, event_type="relay_requested", status=CallStatus.queued.value))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                call = db.scalar(select(Call).where(Call.provider_call_sid == call_sid))
                if call is None:
                    raise HTTPException(status_code=503, detail="Call setup could not be saved.") from None
        audit_event("twilio_voice_webhook", "accepted", action="inbound")
        return _xml(build_voice_twiml(get_settings().twilio_public_base_url, str(call.id)))
    except HTTPException:
        raise
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Call setup is temporarily unavailable.") from None
    finally:
        db.close()


def _transition_call(
    call_id: str,
    call_sid: str,
    *,
    status: CallStatus | None = None,
    event_type: str,
    outcome: str | None = None,
) -> bool:
    """Short-lived DB transaction for a signed, active inbound Relay session."""
    db = SessionLocal()
    try:
        try:
            parsed_id = uuid.UUID(call_id)
        except ValueError:
            return False
        call = db.scalar(
            select(Call).where(Call.id == parsed_id, Call.provider_call_sid == call_sid, Call.simulated == false())
        )
        if call is None:
            return False
        if outcome:
            record_call_outcome(db, call, CallOutcome(outcome))
        if status is not None and call.status not in {CallStatus.completed, CallStatus.failed, CallStatus.disconnected}:
            call.status = status
            if status in {CallStatus.completed, CallStatus.failed, CallStatus.disconnected}:
                call.ended_at = datetime.now(timezone.utc)
            db.add(CallLifecycleEvent(call_id=call.id, event_type=event_type, status=status.value))
        elif outcome:
            db.add(CallLifecycleEvent(call_id=call.id, event_type="conversation_outcome", status=call.status.value))
        db.commit()
        return True
    except (SQLAlchemyError, ValueError):
        db.rollback()
        return False
    finally:
        db.close()


def _handoff_data(value: Any) -> tuple[str, str]:
    reasons = {"wrong_number", "third_party", "callback", "goodbye", "human", "sensitive_request", "uncertain", "identity_unavailable", "provider_error"}
    if not isinstance(value, str) or len(value) > 512:
        return "provider_error", "en"
    try:
        payload = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return "provider_error", "en"
    if not isinstance(payload, dict):
        return "provider_error", "en"
    reason = payload.get("reason")
    language = payload.get("language")
    return (reason if reason in reasons else "provider_error", language if language in {"hi", "en"} else "en")


@router.post("/complete")
async def relay_complete_webhook(request: Request) -> Response:
    form = await _verified_form(request)
    call_sid = str(form.get("CallSid", ""))
    if not _CALL_SID.fullmatch(call_sid):
        raise HTTPException(status_code=422, detail="Invalid call event.")
    reason, language = _handoff_data(form.get("HandoffData"))
    db = SessionLocal()
    try:
        call = db.scalar(select(Call).where(Call.provider_call_sid == call_sid, Call.simulated == false()))
        if call is None:
            raise HTTPException(status_code=404, detail="Call record not found.")
        if call.status not in {CallStatus.completed, CallStatus.failed, CallStatus.disconnected}:
            final_status = CallStatus.failed if reason == "provider_error" or call.status != CallStatus.connected else CallStatus.completed
            call.status = final_status
            call.ended_at = datetime.now(timezone.utc)
            if reason == "callback":
                record_call_outcome(db, call, CallOutcome.callback_requested)
            db.add(CallLifecycleEvent(call_id=call.id, event_type="relay_ended", status=final_status.value))
            db.commit()
        return _xml(build_completion_twiml(reason, language))
    except HTTPException:
        raise
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=503, detail="Call completion could not be saved.") from None
    finally:
        db.close()


def _load_relay_call(call_sid: str, call_id: str) -> bool:
    db = SessionLocal()
    try:
        call = db.scalar(select(Call).where(Call.id == uuid.UUID(call_id), Call.provider_call_sid == call_sid, Call.simulated == false()))
        if call is None or call.direction != "inbound" or call.status != CallStatus.queued:
            return False
        call.status = CallStatus.connected
        db.add(CallLifecycleEvent(call_id=call.id, event_type="relay_connected", status=CallStatus.connected.value))
        db.commit()
        return True
    except (SQLAlchemyError, ValueError):
        db.rollback()
        return False
    finally:
        db.close()


@router.websocket("/relay")
async def relay_websocket(websocket: WebSocket) -> None:
    settings = get_settings()
    if not integration_configured(settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_public_base_url):
        await websocket.close(code=1011, reason="Relay is not configured")
        return
    if websocket.url.query:
        await websocket.close(code=1008, reason="Invalid Relay request")
        return
    signature_url = canonical_websocket_url(settings.twilio_public_base_url, websocket.url.path)
    if not _signature_valid(signature_url, {}, websocket.headers.get("x-twilio-signature")):
        audit_event("twilio_relay", "signature_rejected")
        await websocket.close(code=1008, reason="Invalid Relay request")
        return

    await websocket.accept()
    call_sid: str | None = None
    call_id: str | None = None
    ending = False
    try:
        setup_text = await _receive_relay_frame(websocket, 8)
        if len(setup_text.encode("utf-8")) > MAX_FRAME_BYTES:
            raise RelayProtocolError("Malformed Relay setup message.")
        setup = json.loads(setup_text)
        call_sid, call_id = validate_setup_message(setup, settings.twilio_account_sid)
        if setup.get("connectionType", "initial") != "initial" or not _load_relay_call(call_sid, call_id):
            raise RelayProtocolError("Relay session cannot be resumed or verified.")
        _active_call_sids.add(call_sid)
        session = TwilioRelaySession()
        greeting = session.greeting()
        for outgoing in greeting.messages:
            await websocket.send_json(outgoing)

        while True:
            raw = await _receive_relay_frame(websocket, 120)
            if len(raw.encode("utf-8")) > MAX_FRAME_BYTES:
                raise RelayProtocolError("Relay frame exceeded the size limit.")
            try:
                incoming = json.loads(raw)
                action = session.handle(incoming)
            except (json.JSONDecodeError, RelayProtocolError):
                session.malformed_frames += 1
                if session.malformed_frames >= 3:
                    if call_id and call_sid:
                        _transition_call(call_id, call_sid, status=CallStatus.failed, event_type="relay_protocol_failed")
                    await websocket.close(code=1008, reason="Invalid Relay message")
                    return
                continue

            if action.outcome and call_id and call_sid:
                try:
                    _transition_call(call_id, call_sid, event_type="conversation_outcome", outcome=action.outcome)
                except ValueError:
                    await websocket.close(code=1011, reason="Relay outcome unavailable")
                    return
            if action.terminal_reason and call_id and call_sid:
                ending = True
                terminal_status = (
                    CallStatus.failed
                    if action.terminal_reason == "provider_error"
                    else CallStatus.completed
                )
                _transition_call(call_id, call_sid, status=terminal_status, event_type="relay_ended")
            for outgoing in action.messages:
                await websocket.send_json(outgoing)
            if action.terminal_reason:
                return
    except WebSocketDisconnect:
        if not ending and call_id and call_sid:
            _transition_call(call_id, call_sid, status=CallStatus.disconnected, event_type="relay_disconnected")
    except (TimeoutError, json.JSONDecodeError, RelayProtocolError):
        if call_id and call_sid:
            _transition_call(call_id, call_sid, status=CallStatus.failed, event_type="relay_failed")
        try:
            await websocket.close(code=1011, reason="Relay session failed")
        except RuntimeError:
            pass
    except Exception:
        if call_id and call_sid and not ending:
            _transition_call(call_id, call_sid, status=CallStatus.failed, event_type="relay_failed")
        try:
            await websocket.close(code=1011, reason="Relay session failed")
        except RuntimeError:
            pass
    finally:
        if call_sid:
            _active_call_sids.discard(call_sid)
