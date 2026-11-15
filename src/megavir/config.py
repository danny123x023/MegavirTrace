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
    # Z.ai GLM 5.x "thinks" by default: minutes per answer. Off keeps answers within seconds.
    ai_thinking: bool = False
    # Keys, active service and models chosen in the Admin panel (owner-only file; overrides the
    # values above).  Default: data/ai_settings.json.
    ai_settings_file: str = ""

    # API rate limits for the open data API (FR17) and analysis endpoints
    analysis_per_minute_per_ip: int = 60

    # Import dashboard: actions are allowed from this computer, or with this token (sent by the
    # page as the X-Admin-Token header).  Empty = this computer only.
    admin_token: str = ""
    # Where the Earthdata Login is kept (default: $NETRC, else ~/.netrc).
    netrc_path: str = ""

    # Detailed base map (streets, places, buildings: OpenStreetMap data).  The API relays and keeps
    # the files, so browsers only ever talk to this site.  Empty URL = country outlines only.
    basemap_url: str = "https://tiles.openfreemap.org"
    basemap_style_light: str = "liberty"
    basemap_style_dark: str = "dark"
    basemap_public_path: str = "/api/basemap"  # where browsers reach /basemap (the /api proxy)
    basemap_attribution: str = (
        '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> '
        '<a href="https://www.openmaptiles.org/" target="_blank" rel="noopener">&copy; OpenMapTiles</a> '
        'Data from <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">'
        "&copy; OpenStreetMap contributors</a>"
    )
    basemap_cache_mb: int = 2048
    basemap_per_minute_per_ip: int = 1500


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
