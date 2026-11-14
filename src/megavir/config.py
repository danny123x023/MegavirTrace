"""Server configuration: everything secret or tunable comes from the environment (or .env).

Keys never leave the server: they are read here and used only by the AI clients.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEGAVIR_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://megavir:megavir@localhost:5433/megavir"
    data_dir: Path = ROOT / "data"
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    # which grid versions the API serves: "test", "synthetic" or "real"
    serve_kinds: list[str] = Field(default_factory=lambda: ["real", "test", "synthetic"])

    # AI (optional).  provider: "zai" (default), "openai", "anthropic", "openai_compatible" or "none"
    ai_provider: str = "none"
    ai_model: str = ""
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_hourly_limit_per_ip: int = 20
    ai_daily_cap: int = 500
    ai_max_tokens: int = 1200
    ai_timeout_s: float = 45.0

    # API rate limits for the open data API (FR17) and analysis endpoints
    analysis_per_minute_per_ip: int = 60


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
