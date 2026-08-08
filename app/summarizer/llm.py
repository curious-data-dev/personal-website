"""LLM clients with exponential-backoff retry logic and provider fallback.

Supported providers (tried in order):
- Gemini (google-genai SDK) — free tier: 15 RPM, 1500 RPD
- Groq (groq SDK) — free tier: generous limits, fast inference
- DeepSeek (OpenAI-compatible API) — free tier: 500 req/day

Fallback chain: primary → next available → next available
Each provider gets up to 5 retries with exponential backoff.
"""

import logging
import threading
import time
from typing import Optional

import httpx
from google import genai
from groq import Groq

from app.config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
BASE_DELAY = 2  # seconds → exponential: 2, 4, 8, 16, 32

# Ordered fallback chain — all available providers
_ALL_PROVIDERS = ["deepseek", "groq", "gemini"]

# Usage tracking (in-memory, resets on restart)
_usage = {"calls": 0, "tokens_in": 0, "tokens_out": 0, "errors": 0, "waited_seconds": 0.0}
_last_provider: str = ""


# ---------------------------------------------------------------------------
# Token budget rate limiting
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token), matching existing usage tracking."""
    if not text:
        return 1
    return max(1, len(text) // 4)


class TokenRateLimiter:
    """Throttles LLM calls to stay within a per-minute input-token budget.

    Tracks estimated input tokens sent within a rolling window and blocks
    callers (sleeps) before a request that would exceed the budget. All
    providers share one limiter, so parallel chunk-map calls are serialized
    against the real per-minute quota instead of tripping the API's 429s.
    """

    def __init__(self, tokens_per_minute: int, window_seconds: float = 60.0):
        self.tokens_per_minute = max(1, int(tokens_per_minute))
        self.window_seconds = float(window_seconds)
        self._lock = threading.Lock()
        self._entries: list[tuple[float, int]] = []  # (wall_time, tokens)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        self._entries = [(t, n) for (t, n) in self._entries if t > cutoff]

    def seconds_until_window_reset(self) -> float:
        """Seconds until the current rolling window has capacity again."""
        with self._lock:
            now = time.time()
            self._prune(now)
            if not self._entries:
                return 0.0
            oldest = min(t for t, _ in self._entries)
            return max(0.0, oldest + self.window_seconds - now)

    def acquire(self, token_count: int, on_wait=None) -> float:
        """Block until `token_count` tokens fit within this minute's budget.

        A single request that is larger than the entire per-minute budget can
        never fit in the window — waiting for capacity would hang forever. In
        that case we wait for the window to drain, then let it through anyway
        (the API's own 429 + our retry layer handle the overflow).

        Returns the total time (seconds) spent waiting.
        """
        waited = 0.0
        token_count = max(1, int(token_count))
        oversized = token_count > self.tokens_per_minute
        while True:
            with self._lock:
                now = time.time()
                self._prune(now)
                used = sum(n for _, n in self._entries)
                if oversized:
                    if not self._entries:
                        self._entries.append((now, token_count))
                        return waited
                    oldest = min(t for t, _ in self._entries)
                    delay = oldest + self.window_seconds - now
                elif used + token_count <= self.tokens_per_minute:
                    self._entries.append((now, token_count))
                    return waited
                else:
                    oldest = min(t for t, _ in self._entries)
                    delay = oldest + self.window_seconds - now
            if on_wait:
                on_wait(delay)
            time.sleep(max(0.0, delay))
            waited += max(0.0, delay)


_rate_limiter = TokenRateLimiter(
    settings.llm_input_tokens_per_min,
    settings.rate_limit_window_seconds,
)


def get_usage_stats() -> dict:
    """Return current LLM usage statistics."""
    return dict(_usage)


def get_last_provider() -> str:
    """Return the last successfully used provider."""
    return _last_provider


def is_rate_limit_error(exc: Exception) -> bool:
    """True if the exception looks like a per-minute token / rate-limit error."""
    error_str = str(exc).lower()
    markers = (
        "429",
        "resource_exhausted",
        "rate limit",
        "rate_limit",
        "tokens per minute",
        "token budget",
        "too many requests",
    )
    return any(m in error_str for m in markers)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def call_llm(prompt: str, provider: Optional[str] = None, max_tokens: Optional[int] = None, model: Optional[str] = None, on_progress=None) -> str:
    """Call LLM with retries, falling back through Gemini → Groq → DeepSeek.

    Args:
        prompt: The prompt to send.
        provider: Override the default (\"gemini\", \"groq\", or \"deepseek\").
        max_tokens: Max output tokens. Defaults to settings.llm_max_output_tokens.

    Returns:
        The LLM's response text.

    Raises:
        RuntimeError: After all providers are exhausted.
    """
    if max_tokens is None:
        max_tokens = settings.llm_max_output_tokens
    # Build the fallback chain: primary first, then the rest
    primary = provider or settings.llm_provider
    chain = [primary] + [p for p in _ALL_PROVIDERS if p != primary]

    tried: list[str] = []
    for provider_name in chain:
        if not _provider_configured(provider_name):
            logger.debug(f"Skipping {provider_name}: no API key configured")
            continue

        tried.append(provider_name)
        if on_progress: on_progress(f"Trying {provider_name}...")
        logger.info(f"Trying provider: {provider_name}")

        try:
            result = _call_with_retry(provider_name, prompt, max_tokens, model, on_progress)
            # Track usage (~4 chars per token estimate)
            _usage["calls"] += 1
            _usage["tokens_in"] += len(prompt) // 4
            _usage["tokens_out"] += len(result) // 4
            _last_provider = provider_name
            return result
        except Exception:
            logger.warning(f"{provider_name} failed, trying next provider...")
            continue

    raise RuntimeError(
        f"All providers exhausted. Tried: {', '.join(tried) if tried else 'none'}"
    )


def _call_with_retry(provider_name: str, prompt: str, max_tokens: Optional[int] = None, model: Optional[str] = None, on_progress=None) -> str:
    """Call a single provider with up to MAX_RETRIES attempts.

    Each attempt is first gated by the per-minute token budget limiter, so
    requests are paced rather than bursting past the API quota. Rate-limit
    (429) errors wait for the budget window to reset before retrying.
    """
    if max_tokens is None:
        max_tokens = settings.llm_max_output_tokens
    token_estimate = estimate_tokens(prompt)
    for attempt in range(MAX_RETRIES):
        try:
            waited = _rate_limiter.acquire(
                token_estimate,
                on_wait=lambda delay: (
                    on_progress(f"{provider_name}: waiting {delay:.0f}s for token budget...")
                    if on_progress else None
                ),
            )
            if waited:
                _usage["waited_seconds"] += waited

            if provider_name == "gemini":
                return _call_gemini(prompt, max_tokens, model)
            elif provider_name == "groq":
                return _call_groq(prompt, max_tokens)
            elif provider_name == "deepseek":
                return _call_deepseek(prompt, max_tokens)
        except Exception as e:
            error_str = str(e).lower()
            is_quota_exhausted = "quota" in error_str and "limit: 0" in error_str

            if is_quota_exhausted:
                if on_progress: on_progress(f"{provider_name} quota exhausted, falling back...")
                logger.warning(f"{provider_name} daily quota exhausted, falling back")
                raise  # Bubble up to try next provider

            if is_rate_limit_error(e):
                if attempt < MAX_RETRIES - 1:
                    wait = _rate_limiter.seconds_until_window_reset()
                    if on_progress:
                        on_progress(f"{provider_name} rate limited, retrying in {wait:.0f}s...")
                    logger.warning(
                        f"{provider_name} rate limited, waiting {wait:.0f}s for budget window"
                    )
                    if wait > 0:
                        time.sleep(wait)
                    continue
                logger.error(f"{provider_name} still rate limited after {MAX_RETRIES} attempt(s)")
                raise

            is_retryable = any(
                code in error_str
                for code in (
                    "500",
                    "502",
                    "503",
                    "504",
                    "deadline",
                    "overloaded",
                    "timeout",
                    "timed out",
                    "empty response",
                    "connection reset",
                    "service unavailable",
                )
            )

            if is_retryable and attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2**attempt)
                if on_progress: on_progress(f"{provider_name} retry {attempt+1}/{MAX_RETRIES}...")
                logger.warning(
                    f"{provider_name} attempt {attempt + 1}/{MAX_RETRIES} failed, "
                    f"retrying in {delay}s"
                )
                time.sleep(delay)
                continue

            logger.error(f"{provider_name} failed after {attempt + 1} attempt(s)")
            raise

    raise RuntimeError(f"{provider_name}: all retries exhausted")


def _provider_configured(provider_name: str) -> bool:
    """Check if the provider has an API key configured."""
    key_map = {
        "gemini": settings.gemini_api_key,
        "groq": settings.groq_api_key,
        "deepseek": settings.deepseek_api_key,
    }
    return bool(key_map.get(provider_name))


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------


def _call_gemini(prompt: str, max_tokens: Optional[int] = None, model: Optional[str] = None) -> str:
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not set")
    if max_tokens is None:
        max_tokens = settings.llm_max_output_tokens

    client = genai.Client(
        api_key=settings.gemini_api_key,
        http_options={"timeout": 120000},  # 120 seconds in milliseconds
    )
    response = client.models.generate_content(
        model=model if model else settings.gemini_model,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            temperature=0.5,
            top_p=0.95,
            max_output_tokens=max_tokens,
        ),
    )

    text = _extract_gemini_text(response)

    if not text:
        if response.prompt_feedback and response.prompt_feedback.block_reason:
            raise RuntimeError(f"Gemini blocked: {response.prompt_feedback.block_reason}")
        raise RuntimeError("Gemini returned empty response")

    return text


def _extract_gemini_text(response) -> str:
    """Extract the model's final answer, skipping internal reasoning parts.

    `gemma-4-31b-it` is a thinking model: it returns `thought=True` reasoning
    parts plus a final text part. `response.text` can be None when the output
    budget is consumed by reasoning, even though a valid answer exists.
    """
    parts = []
    for candidate in (response.candidates or []):
        for part in candidate.content.parts:
            if getattr(part, "thought", None):
                continue  # internal reasoning, not the answer
            if part.text:
                parts.append(part.text)

    if parts:
        return "\n".join(parts).strip()

    if response.text:
        return response.text.strip()

    return ""


# ---------------------------------------------------------------------------
# Groq
# ---------------------------------------------------------------------------


def _call_groq(prompt: str, max_tokens: int = 4096, model: Optional[str] = None) -> str:
    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is not set")

    client = Groq(api_key=settings.groq_api_key, timeout=120.0)
    completion = client.chat.completions.create(
        model=model if model else "llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=max_tokens,
    )

    if not completion.choices:
        raise RuntimeError("Groq returned no choices")

    content = completion.choices[0].message.content
    if not content:
        raise RuntimeError("Groq returned empty response")

    return content.strip()


# ---------------------------------------------------------------------------
# DeepSeek (OpenAI-compatible API)
# ---------------------------------------------------------------------------


def _call_deepseek(prompt: str, max_tokens: int = 4096, model: Optional[str] = None) -> str:
    if not settings.deepseek_api_key:
        raise ValueError("DEEPSEEK_API_KEY is not set")

    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model if model else "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.5,
                "max_tokens": max_tokens,
            },
        )
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError:
            raise RuntimeError(f"DeepSeek returned invalid JSON: {response.text[:200]}")

    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("DeepSeek returned no choices")

    content = choices[0].get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("DeepSeek returned empty response")

    return content.strip()
