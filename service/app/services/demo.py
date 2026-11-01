"""Scripted, text-only assignment personas; this module never places calls."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import CallOutcome, Customer
from app.services.conversation import ConversationEngine
from app.services.customer_import import normalize_name_for_comparison

PERSONAS = (
    "right_customer_hindi",
    "wrong_birth_year_english",
    "wrong_number",
    "third_party_callback",
    "silence",
    "do_not_call",
    "third_party_no_callback",
)
SUITE_PERSONAS = (
    "right_customer_hindi", "wrong_birth_year_english", "wrong_number",
    "third_party_callback", "third_party_no_callback", "silence",
)


@dataclass(frozen=True)
class DemoResult:
    outcome: CallOutcome | None
    language: str
    connected: bool
    do_not_call: bool
    callback_at: datetime | None
    simulated_seconds: int
    messages: tuple[tuple[str, str], ...]


def run_persona(customer: Customer, persona: str, now: datetime, timezone_name: str) -> DemoResult:
    if persona not in PERSONAS:
        raise ValueError("Choose one of the documented demo personas.")
    language = "hi" if persona == "right_customer_hindi" else "en" if persona == "wrong_birth_year_english" else customer.preferred_language
    if persona == "silence":
        return DemoResult(CallOutcome.not_connected, language, False, False, None, 15, ())

    if persona == "third_party_no_callback":
        respondent = "I am a relative."
        engine = ConversationEngine()
        transcript: list[tuple[str, str]] = [("assistant", engine.start(language, simulated=True).message), ("customer", respondent)]
        offer = engine.handle(respondent)
        transcript.append(("assistant", offer.message))
        answer = "No"
        transcript.append(("customer", answer))
        final = engine.handle(answer)
        transcript.append(("assistant", final.message))
        return DemoResult(final.outcome, language, True, False, None, 10, tuple(transcript))

    def verify(name: str, year: str) -> bool:
        return bool(
            customer.birth_year
            and normalize_name_for_comparison(name) == normalize_name_for_comparison(customer.display_name)
            and year == str(customer.birth_year)
        )

    engine = ConversationEngine(verify)
    transcript: list[tuple[str, str]] = []

    def bot(response) -> None:
        transcript.append(("assistant", response.message))

    bot(engine.start(language, simulated=True))
    if persona == "wrong_number":
        respondent = "यह गलत नंबर है।" if language == "hi" else "This is a wrong number."
        transcript.append(("customer", respondent))
        final = engine.handle(respondent)
        bot(final)
        return DemoResult(final.outcome, language, True, False, None, 8, tuple(transcript))

    if persona == "third_party_callback":
        respondent = "मैं उनका रिश्तेदार हूँ।" if language == "hi" else "I am a relative."
        transcript.append(("customer", respondent))
        offer = engine.handle(respondent)
        bot(offer)
        callback = "कल शाम चार बजे कॉल करें।" if language == "hi" else "Please call back tomorrow at 4 PM."
        transcript.append(("customer", callback))
        final = engine.handle(callback)
        bot(final)
        local_tomorrow = now.astimezone(ZoneInfo(timezone_name)).date() + timedelta(days=1)
        callback_at = datetime.combine(local_tomorrow, datetime.min.time().replace(hour=16), ZoneInfo(timezone_name))
        return DemoResult(final.outcome, language, True, False, callback_at, 14, tuple(transcript))

    if persona == "do_not_call":
        respondent = "कृपया मुझे दोबारा फोन मत करना।" if language == "hi" else "Please stop calling me."
        transcript.append(("customer", respondent))
        final = engine.handle(respondent)
        bot(final)
        return DemoResult(None, language, True, True, None, 7, tuple(transcript))

    first = "हाँ, मैं ही हूँ।" if language == "hi" else "Yes, I am the intended customer."
    transcript.append(("customer", first))
    engine.handle(first)
    prompt = engine.handle("identity verification" if language == "en" else "पहचान सत्यापन")
    bot(prompt)
    # Identity factors are passed only to the verifier and deliberately omitted
    # from the persisted transcript and all logs.
    transcript.append(("customer", "[name and birth year supplied; identity details redacted]"))
    year = str(customer.birth_year or "0000")
    if persona == "wrong_birth_year_english":
        year = str(max(1900, int(year) - 1))
    final = engine.submit_verification(customer.display_name, year)
    if persona == "wrong_birth_year_english" and final.outcome is None:
        final = engine.submit_verification(customer.display_name, year)
    bot(final)
    return DemoResult(final.outcome, language, True, False, None, 12, tuple(transcript))


def three_line_summary(outcome: CallOutcome | None, connected: bool, callback_at: datetime | None, timezone_name: str) -> str:
    if not connected:
        return "No respondent answered during the simulated 15-second wait.\nVerification was not attempted.\nFinal outcome: Not connected. No callback was requested."
    who = "The intended customer answered; identity details are redacted." if outcome in {CallOutcome.right_customer, CallOutcome.verification_failed} else "A respondent answered; customer identity was not disclosed to another person."
    verification = {
        CallOutcome.right_customer: "Name and birth-year verification passed.",
        CallOutcome.verification_failed: "Verification failed; no expected answer was disclosed.",
    }.get(outcome, "Identity verification was not attempted.")
    if outcome == CallOutcome.callback_requested and callback_at:
        next_action = f"Callback requested for {callback_at.astimezone(ZoneInfo(timezone_name)).strftime('%Y-%m-%d %H:%M %Z')}."
    elif outcome is None:
        next_action = "Do-not-call request recorded; future attempts are blocked."
    else:
        next_action = "No callback requested."
    outcome_text = outcome.value.replace("_", " ").title() if outcome else "Do not call"
    return f"{who}\n{verification}\nFinal outcome: {outcome_text}. {next_action}"
