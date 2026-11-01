import json

from app.core.config import Settings
from app.services import llm


def test_gemini_adapter_only_sends_allowlisted_small_talk(monkeypatch):
    settings = Settings(database_url="postgresql+psycopg://test:test@localhost/test", llm_provider="gemini", gemini_api_key="test-key")
    received = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def read(self, _limit):
            return json.dumps({"candidates": [{"content": {"parts": [{"text": "Hello! I am doing well."}]}}]}).encode()

    def fake_urlopen(request, timeout):
        received.append((request, timeout))
        return Response()

    monkeypatch.setattr(llm, "urlopen", fake_urlopen)
    assert llm.safe_small_talk("Hello!", "en", settings) == "Hello! I am doing well."
    assert received[0][1] == 3
    assert b"Hello!" in received[0][0].data
    assert llm.safe_small_talk("Hello, my name is Alex", "en", settings) is None
    assert len(received) == 1


def test_gemini_sensitive_output_falls_back_without_leaking_error(monkeypatch):
    settings = Settings(database_url="postgresql+psycopg://test:test@localhost/test", llm_provider="gemini", gemini_api_key="test-key")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def read(self, _limit): return b'{"candidates":[{"content":{"parts":[{"text":"Your loan balance is due."}]}}]}'

    monkeypatch.setattr(llm, "urlopen", lambda *_args, **_kwargs: Response())
    assert llm.safe_small_talk("How are you?", "en", settings) is None
