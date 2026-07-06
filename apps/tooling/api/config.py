"""API configuration, sourced from environment (see `.env.example`).

Plain dataclass loaded from `os.environ` — no pydantic-settings dependency.
`get_settings()` is process-cached; tests override via `app.dependency_overrides`
or by constructing `Settings(...)` directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

API_VERSION = "0.1.0"


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    jwt_access_ttl: int
    jwt_refresh_ttl: int
    log_level: str
    # A machine is reported "connected" in /health when its mirror was polled
    # within this many multiples of its poll_interval_seconds (D-F).
    health_stale_multiple: float = 2.0

    @staticmethod
    def from_env() -> Settings:
        url = os.environ.get("DATABASE_URL", "")
        # psycopg3 driver prefix for SQLAlchemy; the .env ships the bare form.
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return Settings(
            database_url=url,
            jwt_secret=os.environ.get("JWT_SECRET", "change-me"),
            jwt_access_ttl=int(os.environ.get("JWT_ACCESS_TTL", "900")),
            jwt_refresh_ttl=int(os.environ.get("JWT_REFRESH_TTL", "86400")),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
