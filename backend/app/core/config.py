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
    max_stops_per_request: int = Field(default=12, ge=2, le=12)
    max_requests_per_ip_per_day: int = Field(default=50, ge=1)
    # Short-window burst limit: requests per minute per IP.
    # Applied in addition to the daily limit to cap bursty automation.
    max_requests_per_ip_per_minute: int = Field(default=10, ge=1)
    # Comma-separated IPs exempt from rate limiting (dev/internal use).
    # Example: RATE_LIMIT_WHITELIST_IPS=203.0.113.1,203.0.113.2
    rate_limit_whitelist_ips: str = Field(
        default="", description="Comma-separated IPs to exempt from rate limiting."
    )
    # Legacy hop-count trust is rejected at startup; use explicit trusted IPs/CIDRs.
    trusted_proxy_count: int = Field(
        default=0,
        ge=0,
        description="Number of trusted reverse-proxy hops that inject X-Forwarded-For.",
    )
    trusted_proxy_ips: str = ""
    rate_limit_storage_uri: str = "memory://"
    provider_calls_per_day: int = Field(default=2000, ge=1)
    max_request_bytes: int = Field(default=16384, ge=1024, le=1048576)
    max_concurrent_requests: int = Field(default=20, ge=1)
    provider_wait_seconds: float = Field(default=2.0, gt=0, le=30)
    cache_cleanup_seconds: int = Field(default=3600, ge=60)
    hsts_enabled: bool = False
    # Maximum concurrent provider (Places + Routes) calls across all in-flight requests.
    # Prevents a burst of simultaneous large plans from exhausting quota or memory.
    max_concurrent_provider_calls: int = Field(
        default=20,
        ge=1,
        description="Global semaphore for outbound Google API calls.",
    )

    # --- Cache ---
    cache_db_path: str = "./cache/places_cache.db"
    cache_ttl_days: int = Field(default=30, ge=1, le=30)

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
