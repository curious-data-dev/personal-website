"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    gemini_api_key: str = ""
    groq_api_key: str = ""
    deepseek_api_key: str = ""
    llm_provider: str = "gemini"  # "gemini", "groq", or "deepseek"
    gemini_model: str = "gemma-4-31b-it"  # Model name for Gemini (e.g. gemma-4-31b-it, gemini-2.5-flash)

    # Email (optional)
    gmail_user: str = ""
    gmail_app_password: str = ""
    recipient_email: str = ""

    # Files & paths
    opml_path: str = "RSS Feeds main.xml"
    data_dir: str = "./data"

    # Scheduler
    scrape_cron_hour: int = 20  # 8 PM IST
    scrape_cron_minute: int = 0
    lookback_hours: int = 48  # 48h window ensures RSS feed delays don't cause missed articles

    # Summarization
    max_article_chars: int = 15000
    min_summary_chars: int = 600
    chunk_size: int = 4000
    chunk_overlap: int = 400

    # Web UI auth
    web_username: str = "admin"
    web_password: str = "changeme"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
