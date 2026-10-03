"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    gemini_api_key: str = ""
    deepseek_api_key: str = ""
    llm_provider: str = "gemini"  # primary provider: "gemini" or "deepseek"
    # One Gemini model for everything (summary, condense, digest). 3.1 flash-lite
    # is non-thinking, fast, and has a 250K TPM budget — unlike the old thinking
    # model (gemma-4-31b-it) whose 16K TPM wall caused frequent failures and
    # paid DeepSeek fallbacks.
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_condense_model: str = "gemini-3.1-flash-lite"
    gemini_digest_model: str = "gemini-3.1-flash-lite"

    # Gemini free-tier pacing, kept under the real limits (15 RPM / 250K TPM /
    # 500 RPD). Enforced by a SQLite-backed limiter shared by the app and worker
    # processes so they never collectively exceed the quota. 0 disables a limit.
    gemini_rpm_limit: int = 14
    gemini_tpm_limit: int = 230000
    gemini_rpd_limit: int = 480

    # DeepSeek is the paid last-resort fallback. 0 = no limit; set an RPD cap to
    # bound cost (exceeding it fails the call instead of spending more).
    deepseek_rpm_limit: int = 0
    deepseek_tpm_limit: int = 0
    deepseek_rpd_limit: int = 0

    llm_max_output_tokens: int = 8192
    # Output cap for the single daily/youtube digest call. 32768 tokens is ~4x
    # the old cap and matches gemini-3.1-flash-lite's generous limit, giving
    # headroom for ~50-article days without truncation (see gemini_digest_model).
    llm_digest_max_output_tokens: int = 32768

    # Email (optional)
    gmail_user: str = ""
    gmail_app_password: str = ""
    recipient_email: str = ""

    # Kindle delivery — export each day's digest to HTML → EPUB and email it
    # to the Kindle "Send to Kindle" address after the daily run.
    # kindle_email is the @kindle.com address; mail is sent from gmail_user
    # (which must be on Amazon's Approved Personal Document E-mail List).
    kindle_email: str = ""
    kindle_enabled: bool = True
    # Where the exported .html / .epub files are written (persisted).
    kindle_export_dir: str = "./data/kindle_exports"

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
    # Target length (chars) for condensed summaries used in daily digests.
    # ~3000 chars ≈ 500 words, matching the condense_summary.md prompt. Also
    # used as the skip-if-short threshold and the truncation fallback.
    condense_target_chars: int = 3000
    # How far back (days) to scan for digests whose articles were linked late
    # (feed lag) and thus need regeneration
    stale_digest_window_days: int = 7

    # Web UI auth
    web_username: str = "admin"
    web_password: str = "changeme"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
