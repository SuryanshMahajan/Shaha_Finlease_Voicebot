"""Twilio Conversation Relay protocol adapter; no dialing client is provided."""
from dataclasses import dataclass
import json
import re
from typing import Any
from urllib.parse import urlparse
from xml.etree.ElementTree import Element, SubElement, tostring

from app.services.conversation import ConversationEngine, ConversationState, FlowResponse

MAX_FRAME_BYTES = 16_384
MAX_VOICE_PROMPT_CHARS = 2_000
_CALL_SID = re.compile(r"^CA[0-9a-fA-F]{32}$")


class RelayProtocolError(ValueError):
    """Invalid or unsupported Relay message. Error text contains no payload."""


def integration_configured(account_sid: str, auth_token: str, public_base_url: str) -> bool:
    return bool(account_sid and auth_token and public_base_url)


def canonical_webhook_url(public_base_url: str, path: str) -> str:
    if not path.startswith("/") or "?" in path or "#" in path:
        raise ValueError("A fixed absolute path is required.")
    parsed = urlparse(public_base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("A configured public HTTPS origin is required.")
    return f"{public_base_url.rstrip('/')}{path}"


def canonical_websocket_url(public_base_url: str, path: str) -> str:
    http_url = canonical_webhook_url(public_base_url, path)
    return "wss://" + http_url.removeprefix("https://")


def validate_twilio_signature(
    auth_token: str,
    url: str,
    parameters: Any,
    signature: str | None,
    *,
    validator_factory=None,
) -> bool:
    """Use the official Twilio SDK RequestValidator; never log its inputs."""
    if not auth_token or not signature or not url:
        return False
    if validator_factory is None:
        try:
            from twilio.request_validator import RequestValidator
        except ImportError:
            return False
        validator_factory = RequestValidator
    try:
        return bool(validator_factory(auth_token).validate(url, parameters, signature))
    except Exception:
        return False


def build_voice_twiml(public_base_url: str, call_record_id: str) -> str:
    """Return TwiML that only accepts inbound call control; it never dials out."""
    relay_url = canonical_websocket_url(public_base_url, "/api/twilio/relay")
    action_url = canonical_webhook_url(public_base_url, "/api/twilio/complete")
    root = Element("Response")
    connect = SubElement(root, "Connect", {"action": action_url, "method": "POST"})
    relay = SubElement(
        connect,
        "ConversationRelay",
        {
            "url": relay_url,
            "language": "en-IN",
            "ttsLanguage": "en-IN",
            "transcriptionLanguage": "en-IN",
            "interruptible": "speech",
            "dtmfDetection": "false",
            "partialPrompts": "false",
        },
    )
    SubElement(relay, "Language", {"code": "en-IN"})
    SubElement(relay, "Language", {"code": "hi-IN"})
    SubElement(relay, "Parameter", {"name": "callRecordId", "value": call_record_id})
    return '<?xml version="1.0" encoding="UTF-8"?>' + tostring(root, encoding="unicode")


def validate_setup_message(message: dict[str, Any], expected_account_sid: str) -> tuple[str, str]:
    if message.get("type") != "setup" or message.get("accountSid") != expected_account_sid:
        raise RelayProtocolError("Invalid Relay setup message.")
    call_sid = message.get("callSid")
    params = message.get("customParameters")
    call_id = params.get("callRecordId") if isinstance(params, dict) else None
    if not isinstance(call_sid, str) or not _CALL_SID.fullmatch(call_sid):
        raise RelayProtocolError("Invalid Relay setup message.")
    if not isinstance(call_id, str) or len(call_id) != 36:
        raise RelayProtocolError("Invalid Relay setup message.")
    try:
        import uuid
        normalized_call_id = str(uuid.UUID(call_id))
    except ValueError as exc:
        raise RelayProtocolError("Invalid Relay setup message.") from exc
    if message.get("direction") != "inbound":
        raise RelayProtocolError("Only inbound Relay sessions are enabled.")
    return call_sid, normalized_call_id


@dataclass(frozen=True)
class RelayAction:
    messages: tuple[dict[str, Any], ...] = ()
    terminal_reason: str | None = None
    outcome: str | None = None
    state: str = ConversationState.ACTIVE.value


_END_REASONS = {
    "wrong_number", "third_party", "callback", "goodbye", "human",
    "sensitive_request", "uncertain", "identity_unavailable", "provider_error",
}


class TwilioRelaySession:
    """One in-memory call session. Conversation content is not logged or persisted."""

    def __init__(self) -> None:
        self.engine = ConversationEngine()
        self.language = "en"
        self.malformed_frames = 0

    def greeting(self) -> RelayAction:
        response = self.engine.start("en", simulated=False)
        return RelayAction((self._text(response.message, "en"),), state=response.state.value)

    def handle(self, message: Any) -> RelayAction:
        if not isinstance(message, dict) or not isinstance(message.get("type"), str):
            raise RelayProtocolError("Malformed Relay message.")
        message_type = message["type"]
        if message_type == "interrupt":
            # Twilio has already stopped current TTS; consume no partial speech.
            return RelayAction(state=self.engine.state.value)
        if message_type == "info":
            return RelayAction(state=self.engine.state.value)
        if message_type == "error":
            return self._terminal("provider_error", None)
        if message_type == "dtmf":
            return self._terminal("uncertain", None)
        if message_type != "prompt":
            raise RelayProtocolError("Unsupported Relay message type.")
        if not isinstance(message.get("last"), bool):
            raise RelayProtocolError("Malformed Relay prompt.")
        if not message["last"]:
            return RelayAction(state=self.engine.state.value)
        text = message.get("voicePrompt")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_VOICE_PROMPT_CHARS:
            raise RelayProtocolError("Malformed Relay prompt.")

        detected = message.get("lang")
        language_switch = None
        detected_base = detected.lower().split("-", 1)[0] if isinstance(detected, str) else ""
        if detected_base == "hi" and self.language != "hi":
            language_switch = "hi"
        elif detected_base == "en" and self.language != "en":
            language_switch = "en"
        prefix: list[dict[str, Any]] = []
        if language_switch:
            self.language = language_switch
            self.engine.handle("hindi" if language_switch == "hi" else "english")
            prefix.append(self._language(language_switch))

        response = self.engine.handle(text)
        if response.intent == "verification":
            # No caller-to-customer binding exists in the voice adapter. Never
            # collect factors and never infer an authorized customer record.
            response = self.engine.handle("human")
            return self._terminal("identity_unavailable", response)
        if response.intent in {"language_hindi", "language_english"}:
            self.language = "hi" if response.intent == "language_hindi" else "en"
            prefix.append(self._language(self.language))
        if response.ended or response.escalate_to_human:
            return self._terminal(self._reason(response), response)
        return RelayAction(tuple(prefix + [self._text(response.message, response.language)]), state=response.state.value)

    def _reason(self, response: FlowResponse) -> str:
        if response.intent == "sensitive_request":
            return "sensitive_request"
        if response.intent in {"wrong_number", "third_party", "callback", "goodbye", "uncertain", "human"}:
            return response.intent
        return "human"

    def _terminal(self, reason: str, response: FlowResponse | None) -> RelayAction:
        if reason not in _END_REASONS:
            reason = "provider_error"
        outcome = response.outcome.value if response and response.outcome else None
        handoff_data = json.dumps({"reason": reason, "language": self.language}, separators=(",", ":"))
        end_message = {"type": "end", "handoffData": handoff_data}
        return RelayAction((end_message,), reason, outcome, self.engine.state.value)

    @staticmethod
    def _text(token: str, language: str) -> dict[str, Any]:
        return {
            "type": "text",
            "token": token,
            "lang": "hi-IN" if language == "hi" else "en-IN",
            "last": True,
            "interruptible": True,
            "preemptible": True,
        }

    @staticmethod
    def _language(language: str) -> dict[str, Any]:
        code = "hi-IN" if language == "hi" else "en-IN"
        return {"type": "language", "ttsLanguage": code, "transcriptionLanguage": code}


def terminal_speech(reason: str, language: str) -> str:
    """Fixed callback speech; never reflect caller/TwiML handoff text."""
    hi = language == "hi"
    return {
        "wrong_number": "Thank you. Goodbye." if not hi else "धन्यवाद। नमस्ते।",
        "third_party": "I cannot discuss customer information. Goodbye." if not hi else "मैं ग्राहक की जानकारी साझा नहीं कर सकता। नमस्ते।",
        "callback": "Your callback request has been recorded. Goodbye." if not hi else "आपका कॉलबैक अनुरोध दर्ज किया गया है। नमस्ते।",
        "goodbye": "Goodbye." if not hi else "नमस्ते।",
        "human": "A human transfer is not available on this prototype. Please contact Shaha Finlease through its official channels." if not hi else "इस प्रोटोटाइप में मानव प्रतिनिधि से जोड़ना उपलब्ध नहीं है। कृपया शाहा फिनलीज़ के आधिकारिक माध्यमों से संपर्क करें।",
        "sensitive_request": "I cannot provide account or financial details. Please contact an authorized representative." if not hi else "मैं खाते या वित्तीय जानकारी नहीं दे सकता। कृपया अधिकृत प्रतिनिधि से संपर्क करें।",
        "uncertain": "I could not understand that clearly. Please contact an authorized representative." if not hi else "मुझे आपकी बात स्पष्ट नहीं समझ आई। कृपया अधिकृत प्रतिनिधि से संपर्क करें।",
        "identity_unavailable": "Identity verification is not available on this automated line. Please contact an authorized representative." if not hi else "इस स्वचालित कॉल पर पहचान सत्यापन उपलब्ध नहीं है। कृपया अधिकृत प्रतिनिधि से संपर्क करें।",
        "provider_error": "The voice service encountered an error. Please contact an authorized representative." if not hi else "वॉइस सेवा में त्रुटि हुई। कृपया अधिकृत प्रतिनिधि से संपर्क करें।",
    }.get(reason, "Goodbye.")


def build_completion_twiml(reason: str, language: str) -> str:
    root = Element("Response")
    SubElement(root, "Say", {"language": "hi-IN" if language == "hi" else "en-IN"}).text = terminal_speech(reason, language)
    SubElement(root, "Hangup")
    return '<?xml version="1.0" encoding="UTF-8"?>' + tostring(root, encoding="unicode")
