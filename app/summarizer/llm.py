"""LLM clients with retry, provider fallback, and shared rate limiting.

Providers (tried in order):
- Gemini (google-genai) — primary, free tier, paced to its real quotas.
- DeepSeek (OpenAI-compatible) — paid; reached only when Gemini is unavailable.

Gemini 3.1 Flash Lite free-tier limits (per project): 15 RPM, 250K TPM, 500 RPD.
We proactively pace to conservative values using a SQLite-backed sliding window
shared by EVERY process (web app + worker), so calls are almost never throttled
and the paid fallback is only used when Gemini genuinely can't serve.

Every call outcome is recorded in `llm_usage_events` so the fallback rate
(Gemini vs DeepSeek) is measurable.
"""

import logging
import threading
import time
from typing import Optional

import httpx
from google import genai

from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
BASE_DELAY = 2  # seconds → exponential: 2, 4, 8, 16, 32
RATE_LIMIT_BACKOFF = 60.0  # wait after a 429 that slipped past the limiter

# Fallback order. The primary (settings.llm_provider) is placed first by
# call_llm(); the rest follow in this order. DeepSeek last = paid last resort.
_ALL_PROVIDERS = ["gemini", "deepseek"]

# Usage tracking (in-memory, resets on restart). Durable per-call records go to
# the llm_usage_events table via _record_usage().
_usage = {"calls": 0, "tokens_in": 0, "tokens_out": 0, "errors": 0, "waited_seconds": 0.0}
_usage_lock = threading.Lock()
_last_provider: str = ""

_rate_table_warned = False


class RateLimitExhausted(RuntimeError):
    """A provider's daily quota is used up — do not wait, fall back instead."""


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token), matching existing usage tracking."""
    if not text:
        return 1
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Shared (cross-process) rate limiting
# ---------------------------------------------------------------------------


class ProviderRateLimiter:
    """Sliding-window limiter for one provider, backed by SQLite.

    Enforces requests/minute, (input+reserved output) tokens/minute, and
    requests/day. Because state lives in the shared DB, the web app and the
    worker draw from one budget. `acquire()` blocks until capacity exists.

    All limits are 0 by default (= disabled).
    """

    def __init__(
        self,
        provider: str,
        rpm: int = 0,
        tpm: int = 0,
        rpd: int = 0,
        window_seconds: float = 60.0,
        daily_window_seconds: float = 86400.0,
    ):
        self.provider = provider
        self.rpm = int(rpm or 0)
        self.tpm = int(tpm or 0)
        self.rpd = int(rpd or 0)
        self.window_seconds = float(window_seconds)
        self.daily_window_seconds = float(daily_window_seconds)

    @property
    def enabled(self) -> bool:
        return bool(self.rpm or self.tpm or self.rpd)

    def acquire(self, tokens: int, on_wait=None) -> float:
        """Block until `tokens` fit the RPM/TPM/RPD budget. Returns seconds waited."""
        global _rate_table_warned
        if not self.enabled:
            return 0.0

        tokens = max(1, int(tokens))
        if self.tpm:
            tokens = min(tokens, self.tpm)  # a single oversized request can't fit

        waited = 0.0
        while True:
            try:
                conn = get_db()
            except Exception as e:  # pragma: no cover - defensive
                logger.warning(f"Rate limiter DB unavailable, proceeding unthrottled: {e}")
                return waited
            try:
                conn.execute("BEGIN IMMEDIATE")
                now = time.time()
                conn.execute(
                    "DELETE FROM llm_rate_events WHERE created_at < ?",
                    (now - self.daily_window_seconds,),
                )
                rows = conn.execute(
                    """SELECT created_at, tokens FROM llm_rate_events
                       WHERE provider = ? AND created_at > ?
                       ORDER BY created_at""",
                    (self.provider, now - self.window_seconds),
                ).fetchall()

                if self.rpd:
                    day_count = conn.execute(
                        "SELECT COUNT(*) FROM llm_rate_events WHERE provider = ? AND created_at > ?",
                        (self.provider, now - self.daily_window_seconds),
                    ).fetchone()[0]
                    if day_count >= self.rpd:
                        conn.commit()
                        raise RateLimitExhausted(
                            f"{self.provider}: daily request quota reached ({self.rpd})"
                        )

                wait = 0.0
                used = sum(r[1] for r in rows)
                if self.rpm and len(rows) >= self.rpm:
                    wait = max(wait, rows[0][0] + self.window_seconds - now)
                if self.tpm and used + tokens > self.tpm:
                    need = used + tokens - self.tpm
                    acc = 0
                    for created_at, tok in rows:
                        acc += tok
                        if acc >= need:
                            wait = max(wait, created_at + self.window_seconds - now)
                            break

                if wait <= 0:
                    conn.execute(
                        "INSERT INTO llm_rate_events (provider, created_at, tokens) VALUES (?, ?, ?)",
                        (self.provider, now, tokens),
                    )
                    conn.commit()
                    return waited
                conn.commit()
            except RateLimitExhausted:
                raise
            except Exception as e:
                if not _rate_table_warned:
                    logger.warning(
                        f"Rate limiter table unavailable ({e}); proceeding unthrottled. "
                        "Is migration 011 applied?"
                    )
                    _rate_table_warned = True
                return waited
            finally:
                conn.close()

            wait = max(wait, 0.01)
            if on_wait:
                on_wait(wait)
            time.sleep(wait)
            waited += wait


_LIMITERS = {
    "gemini": ProviderRateLimiter(
        "gemini",
        rpm=settings.gemini_rpm_limit,
        tpm=settings.gemini_tpm_limit,
        rpd=settings.gemini_rpd_limit,
        window_seconds=settings.rate_limit_window_seconds,
    ),
    "deepseek": ProviderRateLimiter(
        "deepseek",
        rpm=settings.deepseek_rpm_limit,
        tpm=settings.deepseek_tpm_limit,
        rpd=settings.deepseek_rpd_limit,
        window_seconds=settings.rate_limit_window_seconds,
    ),
}


def _record_usage(
    provider: str,
    model: Optional[str],
    event: str,
    *,
    tokens_in: int = 0,
    tokens_out: int = 0,
    waited: float = 0.0,
    detail: str = "",
) -> None:
    """Durably record one call outcome for observability/fallback-rate analysis."""
    try:
        conn = get_db()
        try:
            conn.execute(
                """INSERT INTO llm_usage_events
                   (created_at, provider, model, event, tokens_in, tokens_out, waited, detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (time.time(), provider, model or "", event, tokens_in, tokens_out, waited, detail),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # never let observability break the pipeline
        logger.debug(f"Failed to record LLM usage event ({event}): {e}")


def get_usage_stats() -> dict:
    """Return current in-memory LLM usage statistics (resets on restart)."""
    with _usage_lock:
        return dict(_usage)


def get_last_provider() -> str:
    """Return the last successfully used provider."""
    return _last_provider


def get_llm_usage_breakdown(since: float | None = None) -> list[dict]:
    """Return durable per-provider/event call counts (newest window optional)."""
    conn = get_db()
    try:
        if since is None:
            rows = conn.execute(
                "SELECT provider, event, COUNT(*) n, COALESCE(SUM(tokens_in),0) tin, "
                "COALESCE(SUM(tokens_out),0) tout, COALESCE(SUM(waited),0) waited "
                "FROM llm_usage_events GROUP BY provider, event ORDER BY provider, event"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT provider, event, COUNT(*) n, COALESCE(SUM(tokens_in),0) tin, "
                "COALESCE(SUM(tokens_out),0) tout, COALESCE(SUM(waited),0) waited "
                "FROM llm_usage_events WHERE created_at >= ? "
                "GROUP BY provider, event ORDER BY provider, event",
                (since,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


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


def call_llm(
    prompt: str,
    provider: Optional[str] = None,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
    on_progress=None,
) -> str:
    """Call the LLM with pacing + retries, falling back only after retries.

    Args:
        prompt: The prompt to send.
        provider: Override the primary ("gemini" or "deepseek").
        max_tokens: Max output tokens. Defaults to settings.llm_max_output_tokens.
        model: Override the model (applied to Gemini only).

    Raises:
        RuntimeError: After all providers are exhausted.
    """
    global _last_provider
    if max_tokens is None:
        max_tokens = settings.llm_max_output_tokens

    primary = provider or settings.llm_provider
    chain = [primary] + [p for p in _ALL_PROVIDERS if p != primary]

    tried: list[str] = []
    for provider_name in chain:
        if not _provider_configured(provider_name):
            logger.debug(f"Skipping {provider_name}: no API key configured")
            continue

        tried.append(provider_name)
        if on_progress:
            on_progress(f"Trying {provider_name}...")
        logger.info(f"Trying provider: {provider_name}")

        try:
            result = _call_with_retry(provider_name, prompt, max_tokens, model, on_progress)
            _last_provider = provider_name
            return result
        except RateLimitExhausted as e:
            logger.warning(f"{provider_name} daily quota exhausted, falling back: {e}")
            _record_usage(provider_name, model, "fallback", detail=str(e)[:200])
            continue
        except Exception as e:
            logger.warning(f"{provider_name} failed, trying next provider...")
            _record_usage(provider_name, model, "fallback", detail=str(e)[:200])
            continue

    raise RuntimeError(
        f"All providers exhausted. Tried: {', '.join(tried) if tried else 'none'}"
    )


def _dispatch(provider_name: str, prompt: str, max_tokens: int, model: Optional[str]) -> str:
    if provider_name == "gemini":
        return _call_gemini(prompt, max_tokens, model)
    if provider_name == "deepseek":
        # DeepSeek ignores the Gemini `model` override (it would be an invalid
        # model name); it always uses its own default.
        return _call_deepseek(prompt, max_tokens)
    raise ValueError(f"Unknown provider: {provider_name}")


def _call_with_retry(
    provider_name: str,
    prompt: str,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
    on_progress=None,
) -> str:
    """Call one provider with up to MAX_RETRIES attempts, paced by its limiter."""
    if max_tokens is None:
        max_tokens = settings.llm_max_output_tokens

    limiter = _LIMITERS.get(provider_name)
    reserve = estimate_tokens(prompt) + int(max_tokens or 0)

    for attempt in range(MAX_RETRIES):
        waited = 0.0
        try:
            if limiter is not None and limiter.enabled:
                if on_progress:
                    on_progress_msg = (
                        lambda delay, p=provider_name: on_progress(
                            f"{p}: waiting {delay:.0f}s for rate budget..."
                        )
                    )
                else:
                    on_progress_msg = None
                waited = limiter.acquire(reserve, on_wait=on_progress_msg)
                with _usage_lock:
                    _usage["waited_seconds"] += waited

            result = _dispatch(provider_name, prompt, max_tokens, model)

            with _usage_lock:
                _usage["calls"] += 1
                _usage["tokens_in"] += estimate_tokens(prompt)
                _usage["tokens_out"] += estimate_tokens(result)
            _record_usage(
                provider_name, model, "success",
                tokens_in=estimate_tokens(prompt),
                tokens_out=estimate_tokens(result),
                waited=waited,
            )
            return result

        except RateLimitExhausted:
            raise
        except Exception as e:
            error_str = str(e).lower()
            is_quota_exhausted = "quota" in error_str and "limit: 0" in error_str

            if is_quota_exhausted:
                if on_progress:
                    on_progress(f"{provider_name} quota exhausted, falling back...")
                logger.warning(f"{provider_name} daily quota exhausted, falling back")
                _record_usage(provider_name, model, "quota_exhausted", waited=waited, detail=str(e)[:200])
                raise

            if is_rate_limit_error(e):
                if attempt < MAX_RETRIES - 1:
                    if on_progress:
                        on_progress(f"{provider_name} rate limited, waiting {RATE_LIMIT_BACKOFF:.0f}s...")
                    logger.warning(
                        f"{provider_name} rate limited, waiting {RATE_LIMIT_BACKOFF:.0f}s "
                        "for the real quota window"
                    )
                    _record_usage(
                        provider_name, model, "rate_limited",
                        waited=RATE_LIMIT_BACKOFF, detail=str(e)[:160],
                    )
                    time.sleep(RATE_LIMIT_BACKOFF)
                    continue
                logger.error(f"{provider_name} still rate limited after {MAX_RETRIES} attempt(s)")
                _record_usage(provider_name, model, "rate_limited_exhausted", waited=waited, detail=str(e)[:160])
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
                if on_progress:
                    on_progress(f"{provider_name} retry {attempt + 1}/{MAX_RETRIES}...")
                logger.warning(
                    f"{provider_name} attempt {attempt + 1}/{MAX_RETRIES} failed, "
                    f"retrying in {delay}s"
                )
                time.sleep(delay)
                continue

            logger.error(f"{provider_name} failed after {attempt + 1} attempt(s)")
            with _usage_lock:
                _usage["errors"] += 1
            _record_usage(provider_name, model, "failed", waited=waited, detail=str(e)[:200])
            raise

    raise RuntimeError(f"{provider_name}: all retries exhausted")


def _provider_configured(provider_name: str) -> bool:
    """Check if the provider has an API key configured."""
    key_map = {
        "gemini": settings.gemini_api_key,
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
        http_options={"timeout": 60000},  # 60 seconds in milliseconds
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

    Flash-lite is non-thinking so this is usually just `response.text`, but the
    thought-skipping logic keeps working if a thinking model is ever configured.
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
