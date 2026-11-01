import asyncio

import pytest

from app.services.voice import (
    MockCallAnalysis,
    MockLanguageModel,
    MockSpeechToText,
    MockTextToSpeech,
    ProviderFailure,
    call_with_retries,
    provider_readiness,
    validate_provider_text,
)


def test_provider_timeout_retries_are_bounded_and_success_is_real_result():
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError()
        return "actual provider output"

    assert asyncio.run(call_with_retries(operation, max_attempts=2)) == "actual provider output"
    assert calls == 2


def test_provider_failure_is_returned_after_bounded_attempts():
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        raise ProviderFailure("failed")

    with pytest.raises(ProviderFailure):
        asyncio.run(call_with_retries(operation, max_attempts=3))
    assert calls == 3


def test_provider_timeout_cancels_slow_operation():
    async def operation():
        await asyncio.sleep(1)
        return "too late"

    with pytest.raises(TimeoutError):
        asyncio.run(call_with_retries(operation, timeout_seconds=0.01, max_attempts=1))


def test_readiness_is_secret_free_and_unconfigured():
    readiness = provider_readiness()
    assert {provider.provider for provider in readiness} == {"stt", "llm", "tts", "telephony", "analysis"}
    assert all(not provider.configured and provider.mode == "unconfigured" for provider in readiness)
    assert all("secret" not in repr(provider).lower() for provider in readiness)


def test_mock_adapters_mark_every_result_as_mock_and_simulated():
    async def run():
        results = [
            await MockSpeechToText().transcribe(b"audio", "en"),
            await MockLanguageModel().complete("untrusted prompt"),
            await MockTextToSpeech().synthesize("hello", "en"),
            await MockCallAnalysis().summarize("transcript"),
        ]
        return results

    results = asyncio.run(run())
    assert all(result.provenance == "mock" and result.simulated for result in results)
    assert "NO SPEECH RECOGNITION" in results[0].value
    assert "NO MODEL INVOKED" in results[1].value
    assert "NO ANALYSIS PERFORMED" in results[3].value


@pytest.mark.parametrize("value", [None, "", " \n ", "x" * 10])
def test_malformed_or_oversized_provider_text_is_rejected(value):
    with pytest.raises(ProviderFailure):
        validate_provider_text(value, max_length=5)
