"""Application settings.

All environment variables are read here and nowhere else.
Import `settings` from this module to access them.
"""

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Only read a .env file in local development. In production (APP_ENV=production)
# env vars are injected directly by the platform (Railway) — reading a .env file
# there would let a stale file shadow the real platform values.
_env_file = ".env" if os.getenv("APP_ENV", "development") != "production" else None


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    See `.env.example` for the full list of supported variables.
    """

    model_config = SettingsConfigDict(
        env_file=_env_file,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- API keys (required in production, optional in tests) ---
    anthropic_api_key: str = Field(default="", description="Anthropic API key.")
    google_maps_api_key: str = Field(default="", description="Google Maps Platform API key.")

    # --- App config ---
    app_env: Literal["development", "staging", "production", "test"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    allowed_origins: str = "http://localhost:3000"

    # --- Limits ---
    max_stops_per_request: int = 12
    max_requests_per_ip_per_day: int = 20

    # --- Cache ---
    cache_db_path: str = "./cache/places_cache.db"
    cache_ttl_days: int = 30

    # --- Models ---
    llm_model: str = "claude-haiku-4-5-20251001"

    @property
    def cors_origins(self) -> list[str]:
        """Parse comma-separated allowed origins into a list."""
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Cached so we don't re-parse the environment on every request.
    Tests can call `get_settings.cache_clear()` to force a reload.
    """
    return Settings()


# Module-level convenience handle used across the app.
settings = get_settings()
