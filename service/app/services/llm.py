"""Optional, explicitly enabled model for non-sensitive small talk only."""
import json
import re
from urllib.request import Request, urlopen

from app.core.config import Settings

_PRIVATE_INPUT = re.compile(r"(?:\d{3,}|\b(?:name|birth|year|address|phone|account|loan|balance|due|payment|emi|otp|pin|cvv)\b|@)", re.I)
_SENSITIVE_OUTPUT = re.compile(r"\b(?:account|balance|loan|due|payment|emi|interest|rupee|rs\.?|₹|otp|pin|cvv)\b", re.I)
_SMALL_TALK = re.compile(r"^(?:hi|hello|hey|how are you|how are you doing|good morning|good afternoon|good evening|thank you|thanks|नमस्ते|नमस्कार|आप कैसे हैं)[.!?, ]*$", re.I)


def safe_small_talk(text: str, language: str, settings: Settings) -> str | None:
    """Call the opt-in Gemini API only for low-risk small talk; fail closed."""
    if settings.llm_provider != "gemini" or not settings.gemini_api_key or _PRIVATE_INPUT.search(text) or not _SMALL_TALK.fullmatch(text.strip()):
        return None
    prompt = (
        "You are a brief, polite assistant in a financial-services call simulation. "
        "Respond only to generic greetings or small talk in the requested language. "
        "Do not discuss or infer customer identity, accounts, loans, money, collections, "
        "or policies. If asked about any such topic, say you cannot help and direct the "
        "caller to an authorized representative. Never request credentials. Keep under 35 words.\n"
        f"Language: {'Hindi' if language == 'hi' else 'English'}. Caller: {text[:300]}"
    )
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
    request = Request(endpoint, data=json.dumps({"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2, "maxOutputTokens": 100}}).encode(),
                      headers={"Content-Type": "application/json", "x-goog-api-key": settings.gemini_api_key}, method="POST")
    try:
        with urlopen(request, timeout=3) as response:
            body = json.loads(response.read(64_000))
        value = body["candidates"][0]["content"]["parts"][0]["text"].strip()
        if not value or len(value) > 500 or _SENSITIVE_OUTPUT.search(value):
            return None
        return value
    except Exception:
        # Provider response/errors can contain user content; never log them.
        return None
