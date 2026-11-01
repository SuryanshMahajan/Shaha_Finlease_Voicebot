"""Provider boundaries for a future voicebot integration.

No provider is configured in this project. The development adapter deliberately
does not dial, record audio, or generate customer-facing financial statements.
"""
from dataclasses import dataclass
import asyncio
from collections.abc import Awaitable, Callable
from typing import Generic, Protocol, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ProviderResult(Generic[T]):
    value: T
    provenance: str
    simulated: bool


class SpeechToText(Protocol):
    async def transcribe(self, audio: bytes, language: str) -> ProviderResult[str]: ...


class ConversationOrchestrator(Protocol):
    async def respond(self, text: str, language: str, verified: bool) -> ProviderResult[str]: ...


class LanguageModel(Protocol):
    async def complete(self, prompt: str) -> ProviderResult[str]: ...


class TextToSpeech(Protocol):
    async def synthesize(self, text: str, language: str) -> ProviderResult[bytes]: ...


class Telephony(Protocol):
    async def place_call(self, destination: str) -> "SimulatedCall": ...


class CallStorage(Protocol):
    async def store_recording(self, call_id: str, audio: bytes) -> None: ...
    async def store_transcript(self, call_id: str, transcript: str) -> None: ...


class CallAnalysis(Protocol):
    async def summarize(self, transcript: str) -> ProviderResult[str]: ...
    async def classify_outcome(self, transcript: str) -> ProviderResult[str]: ...


@dataclass(frozen=True)
class SimulatedCall:
    mode: str = "simulated"
    message: str = "Simulation only. No telephone call was placed."


class SafeDevelopmentTelephony:
    """Safe local implementation with no network or dialing capability."""

    async def place_call(self, destination: str) -> SimulatedCall:
        del destination
        return SimulatedCall()


class MockSpeechToText:
    """Test adapter only: emits a marked placeholder, never a transcript of audio."""

    async def transcribe(self, audio: bytes, language: str) -> ProviderResult[str]:
        del audio
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError("Unsupported language.")
        return ProviderResult("[MOCK TRANSCRIPT - NO SPEECH RECOGNITION]", "mock", True)


class MockLanguageModel:
    async def complete(self, prompt: str) -> ProviderResult[str]:
        del prompt
        return ProviderResult("[MOCK RESPONSE - NO MODEL INVOKED]", "mock", True)


class MockTextToSpeech:
    async def synthesize(self, text: str, language: str) -> ProviderResult[bytes]:
        del text
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError("Unsupported language.")
        return ProviderResult(b"MOCK-AUDIO-NOT-SPEECH", "mock", True)


class MockCallAnalysis:
    async def summarize(self, transcript: str) -> ProviderResult[str]:
        del transcript
        return ProviderResult("[MOCK SUMMARY - NO ANALYSIS PERFORMED]", "mock", True)

    async def classify_outcome(self, transcript: str) -> ProviderResult[str]:
        del transcript
        return ProviderResult("not_connected", "mock", True)


class ProviderFailure(RuntimeError):
    """Provider operation failed or returned an unusable response."""


async def call_with_retries(
    operation: Callable[[], Awaitable[T]],
    *,
    timeout_seconds: float = 5.0,
    max_attempts: int = 2,
    retryable: tuple[type[Exception], ...] = (TimeoutError, ProviderFailure),
) -> T:
    """Bound provider latency and retries; never converts failure to success."""
    if timeout_seconds <= 0 or not 1 <= max_attempts <= 3:
        raise ValueError("Provider timeout must be positive and attempts must be between 1 and 3.")
    for attempt in range(max_attempts):
        try:
            return await asyncio.wait_for(operation(), timeout=timeout_seconds)
        except retryable:
            if attempt + 1 == max_attempts:
                raise
    raise AssertionError("unreachable")


@dataclass(frozen=True)
class ProviderReadiness:
    provider: str
    configured: bool
    mode: str


def provider_readiness() -> tuple[ProviderReadiness, ...]:
    """Safe status only. Never reads or returns credential values."""
    return tuple(ProviderReadiness(name, False, "unconfigured") for name in ("stt", "llm", "tts", "telephony", "analysis"))


def validate_provider_text(value: object, *, max_length: int = 20_000) -> str:
    """Reject empty, malformed, or unbounded provider text before downstream use."""
    if not isinstance(value, str):
        raise ProviderFailure("Provider returned an invalid response.")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_length or any(ord(char) < 32 and char not in "\n\t" for char in cleaned):
        raise ProviderFailure("Provider returned an invalid response.")
    return cleaned


SUPPORTED_LANGUAGES = ("hi", "en")
UNVERIFIED_RESPONSE = "Please complete identity verification with an authorized agent."


def protect_response(text: str, verified: bool) -> str:
    """Guard financial disclosure at the orchestration boundary."""
    return text if verified else UNVERIFIED_RESPONSE
