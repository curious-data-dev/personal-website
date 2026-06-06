"""LLM clients with exponential-backoff retry logic.

Supports two providers:
- Gemini (via google-genai SDK) — free tier: 15 RPM, 1500 RPD
- Groq (via groq SDK) — free tier: generous limits, fast inference

Both are tried with up to 5 retries on rate-limit (429) and server (500) errors.
"""

import logging
import time
from typing import Optional

from google import genai
from groq import Groq

from app.config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
BASE_DELAY = 2  # seconds → exponential: 2, 4, 8, 16, 32

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def call_llm(prompt: str, provider: Optional[str] = None) -> str:
    """Call the configured LLM with exponential backoff and provider fallback.

    If the primary provider fails after all retries, automatically falls back
    to the other provider (Gemini ↔ Groq).

    Args:
        prompt: The prompt to send.
        provider: Override the default provider ("gemini" or "groq").

    Returns:
        The LLM's response text.

    Raises:
        RuntimeError: After both providers are exhausted.
    """
    primary = provider or settings.llm_provider
    fallback = "groq" if primary == "gemini" else "gemini"

    for provider_name in (primary, fallback):
        # Skip fallback if no API key configured
        if provider_name == "gemini" and not settings.gemini_api_key:
            logger.warning("Skipping Gemini: no API key")
            continue
        if provider_name == "groq" and not settings.groq_api_key:
            logger.warning("Skipping Groq: no API key")
            continue

        logger.info(f"Using provider: {provider_name}")

        for attempt in range(MAX_RETRIES):
            try:
                if provider_name == "gemini":
                    return _call_gemini(prompt)
                elif provider_name == "groq":
                    return _call_groq(prompt)
            except Exception as e:
                error_str = str(e).lower()
                is_retryable = any(
                    code in error_str
                    for code in ("429", "500", "503", "rate", "overloaded", "timeout")
                )
                is_quota_exhausted = "quota" in error_str and "limit: 0" in error_str

                if is_quota_exhausted:
                    # Daily quota completely exhausted — skip retries, go to fallback
                    logger.warning(f"{provider_name} daily quota exhausted, falling back")
                    break

                if is_retryable and attempt < MAX_RETRIES - 1:
                    delay = BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"{provider_name} call failed (attempt {attempt + 1}/{MAX_RETRIES}), "
                        f"retrying in {delay}s: {e}"
                    )
                    time.sleep(delay)
                    continue

                # Non-retryable error or out of attempts for this provider
                logger.error(f"{provider_name} failed after {attempt + 1} attempt(s): {e}")
                break  # Try fallback provider

    raise RuntimeError(
        f"LLM call failed: both {primary} and {fallback} are exhausted"
    )


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------


def _call_gemini(prompt: str) -> str:
    """Call Gemini via the google-genai SDK v2.x."""
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=settings.gemini_api_key)

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            temperature=0.5,
            top_p=0.95,
            max_output_tokens=2048,
        ),
    )

    if not response.text:
        # Check for safety blocks or empty response
        if response.prompt_feedback and response.prompt_feedback.block_reason:
            raise RuntimeError(
                f"Gemini blocked: {response.prompt_feedback.block_reason}"
            )
        raise RuntimeError("Gemini returned empty response")

    return response.text.strip()


# ---------------------------------------------------------------------------
# Groq
# ---------------------------------------------------------------------------


def _call_groq(prompt: str) -> str:
    """Call Groq via the groq SDK."""
    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is not set")

    client = Groq(api_key=settings.groq_api_key)

    # Use llama-3.3-70b for high quality summaries on free tier
    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=2048,
    )

    if not completion.choices:
        raise RuntimeError("Groq returned no choices")

    content = completion.choices[0].message.content
    if not content:
        raise RuntimeError("Groq returned empty response")

    return content.strip()
