"""Provider-neutral, deterministic conversation state machine.

This module does not call an LLM or access customer data. Identity checks are
delegated to an explicitly injected verifier, normally the existing protected
verification service. Events intentionally omit user text and identity factors.
"""
from dataclasses import dataclass, field
from enum import StrEnum
import re
import unicodedata
from typing import Callable, Literal

from app.models import CallOutcome

Language = Literal["hi", "en"]
Intent = Literal[
    "general_enquiry", "wrong_number", "third_party", "callback", "human",
    "verification", "sensitive_request", "language_hindi", "language_english",
    "goodbye", "uncertain", "do_not_call",
]


class ConversationState(StrEnum):
    NEW = "new"
    ACTIVE = "active"
    VERIFYING = "verifying"
    HANDOFF = "handoff"
    ENDED = "ended"
    CALLBACK_OFFERED = "callback_offered"


@dataclass(frozen=True)
class ConversationEvent:
    kind: str
    state: ConversationState
    # Safe metadata only. Raw user input and verification answers are never kept.
    metadata: dict[str, str | bool] = field(default_factory=dict)


@dataclass(frozen=True)
class FlowResponse:
    message: str
    outcome: CallOutcome | None = None
    ended: bool = False
    escalate_to_human: bool = False
    state: ConversationState = ConversationState.ACTIVE
    language: Language = "en"
    intent: Intent | None = None
    events: tuple[ConversationEvent, ...] = ()


_TEXT = {
    "en": {
        "welcome": "Hello, I am Shaha Finlease's automated assistant. This is a simulated conversation; no phone call or audio recording is taking place. A text transcript of this simulation will be saved. May I speak with the intended customer?",
        "welcome_live": "Hello, I am Shaha Finlease's automated assistant. This session may create an operational call record; voice audio is not stored by this prototype.",
        "language": "You may speak in English or Hindi. You can change language at any time.",
        "verify": "I can help with general enquiries. For customer-specific assistance, please complete the approved name and birth-year identity check.",
        "verify_prompt": "Please say your name and four-digit birth year for the identity check. I will not repeat or retain your answers in application logs.",
        "ask_name": "Please say your full name for the identity check.",
        "ask_year": "Please say your four-digit birth year for the identity check.",
        "verified": "Your identity check is complete. I cannot provide account or financial details in this prototype. I can refer you to an authorized representative.",
        "failure": "I could not verify your identity. I will not share protected information.",
        "wrong": "Thank you for letting me know. I am sorry for the interruption. I will end this interaction.",
        "third_party": "I cannot discuss or confirm any customer information with another person. Could you suggest a suitable time for a return call, without sharing any personal details?",
        "callback": "I will record the callback request. Thank you; I will end this interaction now.",
        "no_callback": "Understood. I will record that another person answered and will not share customer information. Goodbye.",
        "human": "I will refer this to an authorized human representative.",
        "verification_unavailable": "Identity verification is not available on this automated line. I cannot discuss customer-specific or financial information. Please contact an authorized representative.",
        "sensitive": "I cannot share protected customer, account, or financial information. I will refer this to an authorized representative.",
        "uncertain": "I am not confident I understood. I will end this interaction safely; please contact an authorized representative if you need help.",
        "disconnected": "The interaction has ended.",
        "provider_error": "The identity check is temporarily unavailable. Please try again later or contact an authorized representative.",
        "language_changed": "Language changed to English.",
        "do_not_call": "I am sorry. I will stop this interaction and record your request not to be contacted again.",
        "closed": "This interaction has already ended.",
    },
    "hi": {
        "welcome": "नमस्ते, मैं शाहा फिनलीज़ की स्वचालित सहायक हूँ। यह केवल सिमुलेशन है; कोई वास्तविक फ़ोन कॉल या ऑडियो रिकॉर्डिंग नहीं हो रही। इस अभ्यास का टेक्स्ट ट्रांसक्रिप्ट सहेजा जाएगा। क्या मैं इच्छित ग्राहक से बात कर सकती हूँ?",
        "welcome_live": "नमस्ते, मैं शाहा फिनलीज़ की स्वचालित सहायक हूँ। इस सत्र का परिचालन रिकॉर्ड बन सकता है; इस प्रोटोटाइप में आवाज़ सहेजी नहीं जाती।",
        "language": "आप हिंदी या अंग्रेज़ी में बात कर सकते हैं। आप कभी भी भाषा बदल सकते हैं।",
        "verify": "मैं सामान्य जानकारी में सहायता कर सकती हूँ। ग्राहक-विशिष्ट सहायता के लिए स्वीकृत नाम और जन्म-वर्ष पहचान जाँच पूरी करें।",
        "verify_prompt": "पहचान जाँच के लिए कृपया अपना नाम और जन्म का चार अंकों वाला वर्ष बताइए। आपके उत्तर लॉग में नहीं दोहराए या सहेजे जाएँगे।",
        "ask_name": "पहचान जाँच के लिए कृपया अपना पूरा नाम बताइए।",
        "ask_year": "पहचान जाँच के लिए कृपया जन्म का चार अंकों वाला वर्ष बताइए।",
        "verified": "आपकी पहचान जाँच पूरी हुई। इस प्रोटोटाइप में मैं खाते या वित्तीय जानकारी नहीं बता सकती। मैं आपको अधिकृत प्रतिनिधि से जोड़ने का अनुरोध कर सकती हूँ।",
        "failure": "मैं आपकी पहचान की पुष्टि नहीं कर पाई। मैं सुरक्षित जानकारी साझा नहीं करूँगी।",
        "wrong": "बताने के लिए धन्यवाद। हुई असुविधा के लिए क्षमा करें। मैं यह बातचीत समाप्त कर रही हूँ।",
        "third_party": "मैं किसी अन्य व्यक्ति से ग्राहक की जानकारी की चर्चा या पुष्टि नहीं कर सकती। बिना कोई निजी जानकारी बताए, क्या आप दोबारा संपर्क के लिए उचित समय सुझा सकते हैं?",
        "callback": "मैं दोबारा संपर्क का अनुरोध दर्ज करूँगी। धन्यवाद; अब यह बातचीत समाप्त करती हूँ।",
        "no_callback": "ठीक है। मैं दर्ज करूँगी कि किसी अन्य व्यक्ति ने उत्तर दिया और ग्राहक की जानकारी साझा नहीं करूँगी। नमस्ते।",
        "human": "मैं अधिकृत प्रतिनिधि से संपर्क करने का अनुरोध करूँगी।",
        "verification_unavailable": "इस स्वचालित सेवा पर पहचान जाँच उपलब्ध नहीं है। मैं ग्राहक या वित्तीय जानकारी साझा नहीं कर सकती। कृपया अधिकृत प्रतिनिधि से संपर्क करें।",
        "sensitive": "मैं ग्राहक, खाते या वित्तीय जानकारी साझा नहीं कर सकती। मैं अधिकृत प्रतिनिधि से संपर्क करने का अनुरोध करूँगी।",
        "uncertain": "मैं आपकी बात ठीक से समझ नहीं पाई। सुरक्षा के लिए बातचीत समाप्त करती हूँ। सहायता के लिए अधिकृत प्रतिनिधि से संपर्क करें।",
        "disconnected": "बातचीत समाप्त हो गई है।",
        "provider_error": "पहचान जाँच अभी उपलब्ध नहीं है। कृपया बाद में प्रयास करें या अधिकृत प्रतिनिधि से संपर्क करें।",
        "language_changed": "भाषा हिंदी में बदल दी गई है।",
        "do_not_call": "क्षमा करें। मैं यह बातचीत रोक रही हूँ और दोबारा संपर्क न करने का आपका अनुरोध दर्ज करूँगी।",
        "closed": "यह बातचीत पहले ही समाप्त हो चुकी है।",
    },
}


_DNC_HI = tuple(bytes.fromhex(value).decode("utf-8") for value in ('e0a4a6e0a58be0a4ace0a4bee0a4b0e0a4be20e0a4abe0a58be0a4a820e0a4aee0a4a4', 'e0a495e0a589e0a4b220e0a4aee0a4a420e0a495e0a4b0e0a4a8e0a4be', 'e0a4abe0a58be0a4a820e0a4aee0a4a420e0a495e0a4b0e0a4a8e0a4be', 'e0a4b8e0a482e0a4aae0a4b0e0a58de0a49520e0a4a820e0a495e0a4b0e0a587e0a482',))
_HI_HI = tuple(bytes.fromhex(value).decode("utf-8") for value in ('e0a4b9e0a4bfe0a482e0a4a6e0a580', 'e0a4b9e0a4bfe0a4a8e0a58de0a4a6e0a580',))
_WRONG_HI = tuple(bytes.fromhex(value).decode("utf-8") for value in ('e0a497e0a4b2e0a4a420e0a4a8e0a482e0a4ace0a4b0', 'e0a497e0a4b2e0a4a420e0a4a8e0a4aee0a58de0a4ace0a4b0', 'e0a4aee0a581e0a49de0a58720e0a4a8e0a4b9e0a580e0a48220e0a49ce0a4bee0a4a8e0a4a4e0a587',))
_THIRD_HI = tuple(bytes.fromhex(value).decode("utf-8") for value in ('e0a495e0a58be0a48820e0a494e0a4b0', 'e0a4a6e0a582e0a4b8e0a4b0e0a4be20e0a4b5e0a58de0a4afe0a495e0a58de0a4a4e0a4bf', 'e0a4b0e0a4bfe0a4b6e0a58de0a4a4e0a587e0a4a6e0a4bee0a4b0', 'e0a4aae0a4b0e0a4bfe0a4b5e0a4bee0a4b020e0a4b8e0a587',))
_CALLBACK_HI = tuple(bytes.fromhex(value).decode("utf-8") for value in ('e0a495e0a589e0a4b220e0a4ace0a588e0a495', 'e0a495e0a589e0a4b2e0a4ace0a588e0a495', 'e0a4ace0a4bee0a4a620e0a4aee0a587e0a48220e0a4abe0a58be0a4a8', 'e0a4ace0a4bee0a4a620e0a4aee0a587e0a48220e0a495e0a589e0a4b2', 'e0a495e0a4b220e0a4abe0a58be0a4a8',))
_SENSITIVE_HI = tuple(bytes.fromhex(value).decode("utf-8") for value in ('e0a495e0a4b0e0a58de0a49c', 'e0a48be0a4a3', 'e0a4ace0a495e0a4bee0a4afe0a4be', 'e0a495e0a4bfe0a4b8e0a58de0a4a4', 'e0a4b5e0a4b8e0a582e0a4b2e0a580', 'e0a496e0a4bee0a4a4e0a58720e0a495e0a58020e0a49ce0a4bee0a4a8e0a495e0a4bee0a4b0e0a580', 'e0a48be0a4a320e0a4b0e0a4bee0a4b6e0a4bf',))
_HUMAN_HI = tuple(bytes.fromhex(value).decode("utf-8") for value in ('e0a487e0a482e0a4b8e0a4bee0a4a8', 'e0a4aae0a58de0a4b0e0a4a4e0a4bfe0a4a8e0a4bfe0a4a7e0a4bf', 'e0a48fe0a49ce0a587e0a482e0a49f',))
_VERIFY_HI = tuple(bytes.fromhex(value).decode("utf-8") for value in ('e0a4aae0a4b9e0a49ae0a4bee0a4a8', 'e0a4b8e0a4a4e0a58de0a4afe0a4bee0a4aae0a4a8', 'e0a4b8e0a4a4e0a58de0a4afe0a4bee0a4aae0a4bfe0a4a4',))
_GOODBYE_HI = tuple(bytes.fromhex(value).decode("utf-8") for value in ('e0a485e0a4b2e0a4b5e0a4bfe0a4a6e0a4be', 'e0a4ace0a4bee0a4a420e0a4b8e0a4aee0a4bee0a4aae0a58de0a4a4', 'e0a4b8e0a4aee0a4bee0a4aae0a58de0a4a4',))
_INJECTION_HI = tuple(bytes.fromhex(value).decode("utf-8") for value in ('e0a4b8e0a4ade0a58020e0a4a8e0a4bfe0a4afe0a4ae20e0a4ade0a582e0a4b2', 'e0a4a8e0a4bfe0a4b0e0a58de0a4a6e0a587e0a4b620e0a4ade0a582e0a4b2',))

_DIGIT_TRANSLATION = str.maketrans("\u0966\u0967\u0968\u0969\u096a\u096b\u096c\u096d\u096e\u096f", "0123456789")
_NAME_PREFIX = re.compile(r"^(?:my\s+name\s+is|name\s+is|name\s*:|i\s+am|i'm|this\s+is)\s*", re.I)
_YEAR_LABEL = re.compile(r"(?:\s+and)?\s+(?:my\s+)?(?:date\s+of\s+birth|birth\s+year|year)\s*(?:is)?\s*$", re.I)


def extract_verification_factors(text: str, *, allow_bare_name: bool = False) -> tuple[str | None, str | None, bool]:
    """Extract transient name/year factors without keeping them in engine state."""
    value = unicodedata.normalize("NFKC", text).translate(_DIGIT_TRANSLATION).strip()
    year_match = re.search(r"(?<!\d)\d{4}(?!\d)", value)
    year = year_match.group(0) if year_match else None
    name: str | None = None
    if year_match:
        before = _YEAR_LABEL.sub("", value[:year_match.start()]).strip(" ,.;:-")
        after = value[year_match.end():].strip(" ,.;:-")
        candidate = after if _NAME_PREFIX.match(after) else before
        name = _NAME_PREFIX.sub("", candidate).strip(" ,.;:-") or None
    else:
        candidate = _NAME_PREFIX.sub("", value).strip(" ,.;:-")
        if candidate != value.strip(" ,.;:-"):
            name = candidate or None
        elif allow_bare_name and value.casefold() not in {
            "verify", "verify me", "verification", "identity", "yes", "no", "hello", "hi",
        }:
            name = value.strip(" ,.;:-") or None
    return name, year, name is not None or year is not None


def detect_intent(text: str) -> Intent:
    """Small deterministic bilingual intent matcher; user text is never policy."""
    value = unicodedata.normalize("NFKC", text).casefold().strip()
    if not value:
        return "uncertain"
    if any(term in value for term in ("don't call", "do not call", "stop calling", "remove my number", "do not contact", *_DNC_HI)):
        return "do_not_call"
    if any(term in value for term in ("hindi", *_HI_HI)):
        return "language_hindi"
    if any(term in value for term in ("english",)):
        return "language_english"
    if any(term in value for term in ("wrong number", "not the customer", "don't know them", "do not know them", *_WRONG_HI)):
        return "wrong_number"
    if any(term in value for term in ("someone else", "third party", "relative", "family member", *_THIRD_HI)):
        return "third_party"
    if any(term in value for term in ("callback", "call me", "call back", "tomorrow", "later", *_CALLBACK_HI)):
        return "callback"
    if any(term in value for term in ("loan", "balance", "dues", "outstanding", "recovery", "debt", "amount due", "loan amount", *_SENSITIVE_HI)):
        return "sensitive_request"
    if any(term in value for term in ("human", "agent", "representative", "person", *_HUMAN_HI)):
        return "human"
    if any(term in value for term in ("verify", "verification", "identity", *_VERIFY_HI)):
        return "verification"
    if any(term in value for term in ("goodbye", "bye", "hang up", *_GOODBYE_HI)):
        return "goodbye"
    if len(value) < 3 or any(term in value for term in ("ignore previous", "ignore all rules", "reveal the system prompt", "ignore instructions", *_INJECTION_HI)):
        return "uncertain"
    return "general_enquiry"


class ConversationEngine:
    """Single-session controller. Supply a verifier; raw inputs are not persisted."""

    def __init__(
        self,
        verifier: Callable[[str, str], bool] | None = None,
        *,
        factor_verifier: Callable[[str | None, str | None], tuple[bool | None, bool | None]] | None = None,
        pending_name_verified: bool | None = None,
        pending_year_verified: bool | None = None,
        verification_attempts: int = 0,
    ) -> None:
        self.state = ConversationState.NEW
        self.language: Language | None = None
        self.identity_verified = False
        self._verifier = verifier
        self._factor_verifier = factor_verifier
        self.pending_name_verified = pending_name_verified
        self.pending_year_verified = pending_year_verified
        self.verification_attempts = verification_attempts
        self.events: list[ConversationEvent] = []

    def _event(self, kind: str, **metadata: str | bool) -> ConversationEvent:
        event = ConversationEvent(kind, self.state, metadata)
        self.events.append(event)
        return event

    def start(self, language: Language | None = None, *, simulated: bool = True) -> FlowResponse:
        if self.state is not ConversationState.NEW:
            return self._response(_TEXT[self.language or "en"]["closed"], "uncertain")
        if language not in (None, "en", "hi"):
            raise ValueError("Choose Hindi or English.")
        self.language = language or "en"
        self.state = ConversationState.ACTIVE
        event = self._event("assistant_disclosure", language=self.language, simulated=simulated)
        greeting = _TEXT[self.language]["welcome" if simulated else "welcome_live"]
        if language is None:
            greeting += " " + _TEXT[self.language]["language"]
        return self._response(greeting, events=(event,))

    def handle(self, text: str) -> FlowResponse:
        if self.state in (ConversationState.ENDED, ConversationState.HANDOFF):
            return self._response(_TEXT[self.language or "en"]["closed"], "uncertain")
        if self.state is ConversationState.NEW:
            self.start()
        intent = detect_intent(text)
        lang = self.language or "en"
        if intent == "do_not_call":
            self.state = ConversationState.ENDED
            event = self._event("do_not_call_requested")
            return self._response(_TEXT[lang]["do_not_call"], intent, ended=True, events=(event,))
        if self.state is ConversationState.CALLBACK_OFFERED:
            no_text = re.sub(r"[.!?,;:]", "", unicodedata.normalize("NFKC", text).casefold()).strip()
            is_no = no_text in {"no", "no thanks", "no thank you", "\u0928\u0939\u0940\u0902", "\u0928\u0939\u0940"}
            if intent == "callback" or not is_no:
                self.state = ConversationState.ENDED
                outcome = CallOutcome.callback_requested
                event = self._event("conversation_ended", outcome=outcome.value)
                return self._response(_TEXT[lang]["callback"], "callback", outcome=outcome, ended=True, events=(event,))
            self.state = ConversationState.ENDED
            outcome = CallOutcome.third_party_answered
            event = self._event("conversation_ended", outcome=outcome.value)
            return self._response(_TEXT[lang]["no_callback"], "third_party", outcome=outcome, ended=True, events=(event,))
        if intent == "language_hindi":
            return self._switch_language("hi", intent)
        if intent == "language_english":
            return self._switch_language("en", intent)
        if intent == "third_party":
            self.state = ConversationState.CALLBACK_OFFERED
            event = self._event("third_party_callback_offered")
            return self._response(_TEXT[lang]["third_party"], intent, events=(event,))
        if intent in ("wrong_number", "callback", "goodbye"):
            key, outcome = {
                "wrong_number": ("wrong", CallOutcome.wrong_number),
                "callback": ("callback", CallOutcome.callback_requested),
                "goodbye": ("disconnected", CallOutcome.not_connected),
            }[intent]
            self.state = ConversationState.ENDED
            event = self._event("conversation_ended", outcome=outcome.value)
            return self._response(_TEXT[lang][key], intent, outcome=outcome, ended=True, events=(event,))
        if intent == "human":
            self.state = ConversationState.HANDOFF
            event = self._event("human_handoff_requested")
            return self._response(_TEXT[lang]["human"], intent, ended=True, escalate=True, events=(event,))
        if intent in ("uncertain", "sensitive_request"):
            self.state = ConversationState.HANDOFF
            key = "sensitive" if intent == "sensitive_request" else "uncertain"
            event = self._event("human_handoff_requested", reason=intent)
            return self._response(_TEXT[lang][key], intent, ended=True, escalate=True, events=(event,))
        name, year, has_factors = extract_verification_factors(
            text, allow_bare_name=self.state is ConversationState.VERIFYING,
        )
        if self.state is ConversationState.VERIFYING or intent == "verification" or has_factors:
            if self.state is not ConversationState.VERIFYING:
                self.state = ConversationState.VERIFYING
                event = self._event("verification_requested")
            else:
                event = None
            if self._factor_verifier and has_factors:
                name_result, year_result = self._factor_verifier(name, year)
                if name is not None:
                    self.pending_name_verified = name_result
                if year is not None:
                    self.pending_year_verified = year_result
            elif name is not None and year is not None and self._verifier:
                return self.submit_verification(name, year)
            if self.pending_name_verified is not None and self.pending_year_verified is not None:
                return self.submit_verification_result(self.pending_name_verified and self.pending_year_verified)
            if name is None and year is None:
                prompt = _TEXT[lang]["verify_prompt"]
            elif name is None:
                prompt = _TEXT[lang]["ask_name"]
            else:
                prompt = _TEXT[lang]["ask_year"]
            return self._response(prompt, "verification", events=(event,) if event else ())
        # General enquiry: do not answer customer-specific requests here, even
        # after verification; no financial disclosure capability exists.
        if self.identity_verified:
            self.state = ConversationState.HANDOFF
            event = self._event("human_handoff_requested", reason="customer_specific_help")
            return self._response(_TEXT[lang]["verified"], "general_enquiry", ended=True, escalate=True, events=(event,))
        event = self._event("verification_required")
        return self._response(_TEXT[lang]["verify"], "general_enquiry", events=(event,))

    def submit_verification(self, display_name: str, birth_year: str) -> FlowResponse:
        if self.state is not ConversationState.VERIFYING:
            return self._response(_TEXT[self.language or "en"]["closed"], "verification")
        # Do not retain caller-provided factors in state, events, or responses.
        verifier = self._verifier
        if verifier is None:
            event = self._event("verification_unavailable")
            return self._response(_TEXT[self.language or "en"]["provider_error"], "verification", events=(event,))
        try:
            verified = bool(verifier(display_name, birth_year))
        except Exception:
            event = self._event("verification_unavailable")
            return self._response(_TEXT[self.language or "en"]["provider_error"], "verification", events=(event,))
        return self.submit_verification_result(verified)

    def submit_verification_result(self, verified: bool) -> FlowResponse:
        """Complete one factor pair without retaining the submitted factors."""
        self.identity_verified = verified
        self.verification_attempts += 1
        lang = self.language or "en"
        if verified:
            self.pending_name_verified = None
            self.pending_year_verified = None
            self.state = ConversationState.HANDOFF
            event = self._event("identity_verification", verified=True)
            return self._response(_TEXT[lang]["verified"], "verification", outcome=CallOutcome.right_customer, ended=True, escalate=True, events=(event,))
        if self.verification_attempts < 2:
            self.pending_name_verified = None
            self.pending_year_verified = None
            event = self._event("identity_verification", verified=False)
            return self._response(_TEXT[lang]["verify_prompt"], "verification", events=(event,))
        self.state = ConversationState.ENDED
        self.pending_name_verified = None
        self.pending_year_verified = None
        event = self._event("identity_verification", verified=False)
        return self._response(_TEXT[lang]["failure"], "verification", outcome=CallOutcome.verification_failed, ended=True, events=(event,))

    def _switch_language(self, language: Language, intent: Intent) -> FlowResponse:
        self.language = language
        event = self._event("language_changed", language=language)
        return self._response(_TEXT[language]["language_changed"], intent, events=(event,))

    def _response(
        self,
        message: str,
        intent: Intent | None = None,
        *,
        outcome: CallOutcome | None = None,
        ended: bool = False,
        escalate: bool = False,
        events: tuple[ConversationEvent, ...] = (),
    ) -> FlowResponse:
        return FlowResponse(message, outcome, ended, escalate, self.state, self.language or "en", intent, events)


class DevelopmentConversation:
    """Backward-compatible deterministic facade used by local simulation tests."""

    def __init__(self, language: Language) -> None:
        if language not in _TEXT:
            raise ValueError("Choose Hindi or English.")
        self.language = language
        self.identity_verified = False

    def start(self) -> FlowResponse:
        return FlowResponse(_TEXT[self.language]["welcome"], language=self.language)

    def request_verification(self) -> FlowResponse:
        return FlowResponse(_TEXT[self.language]["verify_prompt"], state=ConversationState.VERIFYING, language=self.language)

    def record_verification(self, verified: bool) -> FlowResponse:
        self.identity_verified = verified
        return FlowResponse(
            _TEXT[self.language]["verified"] if verified else _TEXT[self.language]["failure"],
            outcome=CallOutcome.right_customer if verified else CallOutcome.verification_failed,
            ended=not verified,
            escalate_to_human=verified,
            state=ConversationState.HANDOFF if verified else ConversationState.ENDED,
            language=self.language,
        )

    def handle(self, intent: Intent) -> FlowResponse:
        mapping = {
            "wrong_number": ("wrong", CallOutcome.wrong_number, True, False),
            "third_party": ("third_party", CallOutcome.third_party_answered, True, False),
            "callback": ("callback", CallOutcome.callback_requested, True, False),
            "disconnected": ("disconnected", CallOutcome.not_connected, True, False),
            "human": ("human", None, True, True),
            "uncertain": ("uncertain", None, True, True),
            "sensitive_request": ("sensitive", None, True, True),
        }
        if intent in mapping:
            key, outcome, ended, escalate = mapping[intent]
            return FlowResponse(_TEXT[self.language][key], outcome, ended, escalate, ConversationState.HANDOFF if escalate else ConversationState.ENDED, self.language, intent)
        if intent == "verification_failed":
            return self.record_verification(False)
        if intent == "verified":
            return self.record_verification(True)
        return self.request_verification()
