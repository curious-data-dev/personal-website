"""Tests for the shared provider rate limiter, fallback chain, and retry behaviour."""

import pytest

from app.summarizer import llm
from app.summarizer.llm import (
    ProviderRateLimiter,
    RateLimitExhausted,
    estimate_tokens,
    is_rate_limit_error,
)


class FakeClock:
    """Controllable time source + sleep recorder for deterministic timing tests."""

    def __init__(self, start=1000.0):
        self.now = start
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, secs):
        self.sleeps.append(secs)
        self.now += secs


@pytest.fixture
def fake_clock(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(llm.time, "time", clock.time)
    monkeypatch.setattr(llm.time, "sleep", clock.sleep)
    return clock


def test_estimate_tokens_is_character_ratio():
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 8000) == 2000


def test_is_rate_limit_error_detects_common_messages():
    assert is_rate_limit_error(RuntimeError("429 RESOURCE_EXHAUSTED rate limit"))
    assert is_rate_limit_error(RuntimeError("tokens per minute exceeded"))
    assert is_rate_limit_error(RuntimeError("rate limit exceeded"))
    assert is_rate_limit_error(RuntimeError("too many requests, try again later"))
    assert not is_rate_limit_error(RuntimeError("some other error"))
    assert not is_rate_limit_error(RuntimeError("quota exceeded"))  # daily quota, not per-minute


# ---------------------------------------------------------------------------
# ProviderRateLimiter (SQLite-backed, shared across processes)
# ---------------------------------------------------------------------------


def test_disabled_limiter_is_noop(isolated_db):
    limiter = ProviderRateLimiter("gemini", rpm=0, tpm=0, rpd=0)
    assert limiter.enabled is False
    assert limiter.acquire(10**9) == 0.0


def test_limiter_enforces_requests_per_minute(isolated_db, fake_clock):
    limiter = ProviderRateLimiter("gemini", rpm=3, tpm=0, rpd=0, window_seconds=60)
    assert limiter.acquire(1) == 0.0
    assert limiter.acquire(1) == 0.0
    assert limiter.acquire(1) == 0.0
    # 4th request in the window must wait for the first to age out.
    waited = limiter.acquire(1)
    assert waited >= 59
    # After the wait the window has room again.
    assert limiter.acquire(1) == 0.0


def test_limiter_enforces_tokens_per_minute(isolated_db, fake_clock):
    limiter = ProviderRateLimiter("gemini", rpm=0, tpm=10, rpd=0, window_seconds=60)
    assert limiter.acquire(4) == 0.0
    assert limiter.acquire(4) == 0.0
    # 8 used + 4 requested > 10 → must wait.
    assert limiter.acquire(4) >= 59


def test_limiter_daily_quota_raises_instead_of_waiting(isolated_db, fake_clock):
    limiter = ProviderRateLimiter("gemini", rpm=0, tpm=0, rpd=2)
    assert limiter.acquire(1) == 0.0
    assert limiter.acquire(1) == 0.0
    with pytest.raises(RateLimitExhausted):
        limiter.acquire(1)


def test_limiter_is_shared_between_connections(isolated_db, fake_clock):
    """Two limiter instances (two processes) draw from one DB budget."""
    process_a = ProviderRateLimiter("gemini", rpm=3, tpm=0, rpd=0)
    process_b = ProviderRateLimiter("gemini", rpm=3, tpm=0, rpd=0)
    assert process_a.acquire(1) == 0.0
    assert process_b.acquire(1) == 0.0
    assert process_a.acquire(1) == 0.0
    # Cross-process budget is exhausted → process_b must wait.
    assert process_b.acquire(1) >= 59


# ---------------------------------------------------------------------------
# Fallback chain
# ---------------------------------------------------------------------------


def test_chain_contains_only_gemini_and_deepseek():
    assert llm._ALL_PROVIDERS == ["gemini", "deepseek"]
    assert not hasattr(llm, "_call_groq")


def _configure(monkeypatch, gemini="k", deepseek="k"):
    monkeypatch.setattr(llm.settings, "gemini_api_key", gemini)
    monkeypatch.setattr(llm.settings, "deepseek_api_key", deepseek)
    monkeypatch.setattr(llm, "_LIMITERS", {})  # no pacing in these unit tests


def test_deepseek_used_only_after_gemini_retries(isolated_db, monkeypatch, fake_clock):
    _configure(monkeypatch)
    gemini_calls = {"n": 0}
    deepseek_calls = {"n": 0}

    def failing_gemini(prompt, max_tokens=None, model=None):
        gemini_calls["n"] += 1
        raise RuntimeError("Gemini returned empty response")  # retryable

    def ok_deepseek(prompt, max_tokens=4096, model=None):
        deepseek_calls["n"] += 1
        return "deepseek answer"

    monkeypatch.setattr(llm, "_call_gemini", failing_gemini)
    monkeypatch.setattr(llm, "_call_deepseek", ok_deepseek)

    result = llm.call_llm("hello", max_tokens=64)

    assert result == "deepseek answer"
    assert gemini_calls["n"] == llm.MAX_RETRIES  # exhausted before falling back
    assert deepseek_calls["n"] == 1
    assert llm.get_last_provider() == "deepseek"


def test_rate_limit_waits_for_real_window_then_succeeds(isolated_db, monkeypatch, fake_clock):
    _configure(monkeypatch)
    calls = {"n": 0}

    def flaky_gemini(prompt, max_tokens=None, model=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("429 RESOURCE_EXHAUSTED rate limit exceeded")
        return "ok"

    monkeypatch.setattr(llm, "_call_gemini", flaky_gemini)

    result = llm.call_llm("a" * 4000, max_tokens=64, provider="gemini")

    assert result == "ok"
    assert calls["n"] == 2
    assert any(s >= llm.RATE_LIMIT_BACKOFF for s in fake_clock.sleeps)


def test_success_records_provider(isolated_db, monkeypatch, fake_clock):
    _configure(monkeypatch)
    monkeypatch.setattr(llm, "_call_gemini", lambda *a, **k: "answer")

    assert llm.call_llm("hi", provider="gemini", max_tokens=64) == "answer"
    assert llm.get_last_provider() == "gemini"


# ---------------------------------------------------------------------------
# Gemini response parsing
# ---------------------------------------------------------------------------


class FakeGeminiResponse:
    """Minimal stand-in for genai GenerateContentResponse with thought parts."""

    def __init__(self, text=None, thought_text=None, block_reason=None):
        self.text = text
        self.prompt_feedback = type("FB", (), {"block_reason": block_reason})()
        parts = []
        if thought_text:
            parts.append(type("P", (), {"thought": True, "text": thought_text})())
        if text:
            parts.append(type("P", (), {"thought": None, "text": text})())
        self.candidates = [type("C", (), {"content": type("Co", (), {"parts": parts})()})]


def test_gemini_text_extraction_skips_thought_parts(monkeypatch):
    """Thinking models return reasoning parts; the answer must still be extracted."""
    class FakeModels:
        def generate_content(self, *a, **kw):
            return FakeGeminiResponse(text="Final answer.", thought_text="internal reasoning")

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        models = FakeModels()

    monkeypatch.setattr(llm, "genai", type("G", (), {"Client": FakeClient, "types": llm.genai.types})())

    assert llm._call_gemini("prompt") == "Final answer."


def test_gemini_text_extraction_empty_when_no_answer(monkeypatch):
    """A response with only reasoning (no final text) must still raise cleanly."""
    class FakeModels:
        def generate_content(self, *a, **kw):
            return FakeGeminiResponse(text=None, thought_text="only reasoning")

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        models = FakeModels()

    monkeypatch.setattr(llm, "genai", type("G", (), {"Client": FakeClient, "types": llm.genai.types})())

    with pytest.raises(RuntimeError, match="empty response"):
        llm._call_gemini("prompt")
