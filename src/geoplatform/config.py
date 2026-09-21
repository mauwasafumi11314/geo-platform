"""Runtime configuration, read once from the environment.

Everything the application needs to reach the database lives here. Nothing is
hardcoded: credentials come from DATABASE_URL, which docker compose supplies
from .env and CI supplies from the workflow environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

DEFAULT_DATABASE_URL = "postgresql://geo:geo@localhost:5432/geoplatform"


def _env_int(
    name: str, default: int, *, minimum: int | None = None, maximum: int | None = None
) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}, got {value}")
    return value


def normalise_dsn(url: str) -> str:
    """Strip any SQLAlchemy-style driver suffix.

    ``postgresql+asyncpg://...`` is a valid SQLAlchemy URL but asyncpg and
    psycopg both reject it, so accept either spelling and hand the drivers the
    plain form.
    """
    scheme, sep, rest = url.partition("://")
    if not sep:
        return url
    return f"{scheme.split('+', 1)[0]}{sep}{rest}"


@dataclass(frozen=True)
class Settings:
    """Immutable view of the process environment."""

    database_url: str
    pool_min_size: int
    pool_max_size: int
    command_timeout: int
    tile_extent: int
    tile_buffer: int
    tile_cache_seconds: int
    max_features: int
    cors_origins: tuple[str, ...]

    @property
    def dsn(self) -> str:
        return normalise_dsn(self.database_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    origins = os.getenv("CORS_ORIGINS", "http://localhost:5173")
    return Settings(
        database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        pool_min_size=_env_int("DB_POOL_MIN_SIZE", 1, minimum=0),
        pool_max_size=_env_int("DB_POOL_MAX_SIZE", 10, minimum=1),
        command_timeout=_env_int("DB_COMMAND_TIMEOUT", 30, minimum=1),
        # 4096 is the MVT convention; the buffer stops symbols being clipped
        # at tile seams.
        tile_extent=_env_int("TILE_EXTENT", 4096, minimum=256, maximum=16384),
        tile_buffer=_env_int("TILE_BUFFER", 64, minimum=0, maximum=1024),
        tile_cache_seconds=_env_int("TILE_CACHE_SECONDS", 300, minimum=0),
        max_features=_env_int("MAX_FEATURES", 5000, minimum=1),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
    )
