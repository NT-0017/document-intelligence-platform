"""Application settings, read from environment variables / .env (never hardcoded)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Document Intelligence API"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    llm_timeout_seconds: int = 90
    database_url: str = "sqlite:///./data/documents.db"
    max_pages: int = 3
    max_file_size_mb: int = 10
    # A check passes if |calculated - reported| <= tolerance (absolute, in document units).
    # Statements are usually in crore/million with 2 decimals, so rounding drift can add up.
    tolerance_statement: float = 1.0
    # Invoices/receipts: allow 0.05 for cash-rounding (e.g. Malaysian 5-sen rounding).
    tolerance_invoice: float = 0.05
    log_level: str = "INFO"
    # repo-root/frontend by default (templates + static); override with FRONTEND_DIR
    frontend_dir: str = str(Path(__file__).resolve().parents[3] / "frontend")

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
