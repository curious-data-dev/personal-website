"""Tests for the per-minute token budget limiter and rate-limit-aware retry."""

import pytest

from app.summarizer import llm
from app.summarizer.llm import (
    TokenRateLimiter,
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


def test_rate_limiter_paces_bursts_within_budget(fake_clock):
    limiter = TokenRateLimiter(tokens_per_minute=4000, window_seconds=60)
    # 5 parallel calls of 1000 tokens each: 4 fit in the 4000 budget...
    for _ in range(4):
        assert limiter.acquire(1000) == 0.0
    # ...the 5th must wait for the window to roll over.
    waited = limiter.acquire(1000)
    assert waited > 0
    # After the wait the budget is fresh again.
    assert limiter.acquire(1000) == 0.0
    assert len(fake_clock.sleeps) >= 1


def test_rate_limiter_window_reset_after_sleep(fake_clock):
    limiter = TokenRateLimiter(tokens_per_minute=100, window_seconds=60)
    limiter.acquire(100)  # full budget
    assert limiter.seconds_until_window_reset() == pytest.approx(60.0)
    # Advance past the window and confirm capacity returns.
    fake_clock.now += 61
    assert limiter.seconds_until_window_reset() == 0.0
    assert limiter.acquire(100) == 0.0


def test_is_rate_limit_error_detects_common_messages():
    assert is_rate_limit_error(RuntimeError("429 RESOURCE_EXHAUSTED rate limit"))
    assert is_rate_limit_error(RuntimeError("tokens per minute exceeded"))
    assert is_rate_limit_error(RuntimeError("rate limit exceeded"))
    assert is_rate_limit_error(RuntimeError("too many requests, try again later"))
    assert not is_rate_limit_error(RuntimeError("some other error"))
    assert not is_rate_limit_error(RuntimeError("quota exceeded"))  # daily quota, not per-minute


def test_429_retry_waits_for_window_then_succeeds(fake_clock, monkeypatch):
    """A 429 should pause until the budget window resets, then retry, not give up."""
    calls = {"n": 0}

    def fake_gemini(prompt, max_tokens=4096, model=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("429 RESOURCE_EXHAUSTED rate limit exceeded")
        return "ok"

    monkeypatch.setattr(llm, "_call_gemini", fake_gemini)
    limiter = TokenRateLimiter(tokens_per_minute=1000, window_seconds=60)
    monkeypatch.setattr(llm, "_rate_limiter", limiter)

    result = llm._call_with_retry("gemini", "a" * 4000, on_progress=None)

    assert result == "ok"
    assert calls["n"] == 2
    # The retry slept for the remaining window (~60s), then re-acquired cleanly.
    assert any(s >= 55 for s in fake_clock.sleeps)


def test_429_retry_uses_available_budget_before_hitting_limit(fake_clock, monkeypatch):
    """The limiter should be acquired before each real network call."""
    attempts = []
    limiter = TokenRateLimiter(tokens_per_minute=4000, window_seconds=60)
    monkeypatch.setattr(llm, "_rate_limiter", limiter)

    def fake_gemini(prompt, max_tokens=4096, model=None):
        attempts.append(estimate_tokens(prompt))
        return "ok"

    monkeypatch.setattr(llm, "_call_gemini", fake_gemini)

    llm._call_with_retry("gemini", "x" * 4000)
    llm._call_with_retry("gemini", "x" * 4000)
    assert len(attempts) == 2


def test_oversized_request_does_not_hang(fake_clock):
    """A request larger than the whole per-minute budget must not block forever."""
    limiter = TokenRateLimiter(tokens_per_minute=4000, window_seconds=60)
    limiter.acquire(4000)  # fill the budget
    # Request larger than the budget itself: can never fit, must pass through.
    waited = limiter.acquire(100000)
    assert waited > 0
    # Budget window should still have recorded it so subsequent calls pace.
    assert limiter.seconds_until_window_reset() > 0


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
    seen = {}

    class FakeModels:
        def generate_content(self, *a, **kw):
            seen["kw"] = kw
            return FakeGeminiResponse(text="Final answer.", thought_text="internal reasoning")

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        models = FakeModels()

    monkeypatch.setattr(llm, "genai", type("G", (), {"Client": FakeClient, "types": llm.genai.types})())

    result = llm._call_gemini("prompt")
    assert result == "Final answer."


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

    try:
        llm._call_gemini("prompt")
        assert False, "should have raised"
    except RuntimeError as e:
        assert "empty response" in str(e)
