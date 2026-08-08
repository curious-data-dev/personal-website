"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    gemini_api_key: str = ""
    groq_api_key: str = ""
    deepseek_api_key: str = ""
    llm_provider: str = "gemini"  # "gemini", "groq", or "deepseek"
    gemini_model: str = "gemma-4-31b-it"  # Model name for Gemini (e.g. gemma-4-31b-it, gemini-2.5-flash)
    # Model for the condensation step only. gemma-4-31b-it is a thinking model
    # that burns its output budget on internal reasoning, so short-output tasks
    # like condensation frequently return empty responses or 504s. Use a fast
    # non-thinking model here; the heavier thinking model stays for article
    # summaries and the daily digest.
    gemini_condense_model: str = "gemini-3.1-flash-lite"
    # Model for daily/youtube digest generation. A digest is ONE LLM call that
    # must render every story of the day, so it needs a large output budget.
    # gemini-3.1-flash-lite is fast and non-thinking with a 64K output limit
    # (vs gemma-4-31b-it which burns output on reasoning), so it can produce
    # long, detailed digests without truncation.
    gemini_digest_model: str = "gemini-3.1-flash-lite"

    # gemma-4-31b-it is a thinking model: it spends output tokens on internal
    # reasoning BEFORE producing the answer. A 4096-token output budget gets
    # fully consumed by reasoning (empty responses ~2/3 of the time), so we
    # raise the default to leave room for reasoning + the final answer.
    llm_max_output_tokens: int = 8192
    # Output cap for the single daily/youtube digest call. 32768 tokens is ~4x
    # the old cap and matches gemini-3.1-flash-lite's generous limit, giving
    # headroom for ~50-article days without truncation (see gemini_digest_model).
    llm_digest_max_output_tokens: int = 32768

    # Email (optional)
    gmail_user: str = ""
    gmail_app_password: str = ""
    recipient_email: str = ""

    # Files & paths
    opml_path: str = "RSS Feeds main.xml"
    data_dir: str = "./data"

    # Scheduler
    scrape_cron_hour: int = 8   # 8 AM IST
    scrape_cron_minute: int = 0
    # 96h (4-day) window: The Hindu Evening Wrap and other feeds expose items
    # 1-2 days late, so a 48h window let those fall out before being fetched.
    lookback_hours: int = 96

    # Durable worker and YouTube transcript providers
    worker_poll_seconds: int = 5
    worker_lease_minutes: int = 360
    youtube_transcript_providers: str = "supadata,scribetube,transcriptapi_io"
    supadata_api_key: str = ""
    supadata_monthly_limit: int = 100
    scribetube_api_key: str = ""
    scribetube_monthly_limit: int = 1000
    transcriptapi_io_api_key: str = ""
    transcriptapi_io_monthly_limit: int = 100
    youtube_job_max_attempts: int = 5

    # Summarization
    max_article_chars: int = 15000
    min_summary_chars: int = 600
    chunk_size: int = 4000
    chunk_overlap: int = 400
    # Per-minute input-token budget for the LLM API. gemini-3.1-flash-lite's
    # free tier allows 250k TPM, so pace against the real quota (leave a little
    # headroom for burst safety) instead of the old 16k that throttled us early.
    llm_input_tokens_per_min: int = 200000
    # Rolling window (seconds) for the per-minute token budget
    rate_limit_window_seconds: int = 60
    # Target length (chars) for condensed summaries used in daily digests
    condense_target_chars: int = 600
    # How far back (days) to scan for digests whose articles were linked late
    # (feed lag) and thus need regeneration
    stale_digest_window_days: int = 7

    # Web UI auth
    web_username: str = "admin"
    web_password: str = "changeme"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
