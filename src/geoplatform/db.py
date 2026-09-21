"""asyncpg connection pool management.

A single pool is created on application startup and torn down on shutdown.
Raw asyncpg is used rather than an ORM: every query in this service is
hand-written SQL that leans on PostGIS functions, and the tile endpoint
returns bytes straight from the database.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

from geoplatform.config import Settings, get_settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Decode JSONB into Python objects instead of leaving it as text."""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def create_pool(settings: Settings | None = None) -> asyncpg.Pool:
    """Create the process-wide pool. Idempotent."""
    global _pool
    if _pool is not None:
        return _pool

    settings = settings or get_settings()
    _pool = await asyncpg.create_pool(
        dsn=settings.dsn,
        min_size=settings.pool_min_size,
        max_size=settings.pool_max_size,
        command_timeout=settings.command_timeout,
        init=_init_connection,
    )
    logger.info("database pool ready (max_size=%s)", settings.pool_max_size)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("database pool closed")


def get_pool() -> asyncpg.Pool:
    """Return the live pool, or fail loudly if startup never ran."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialised; did the app lifespan run?")
    return _pool


async def healthcheck() -> dict[str, Any]:
    """Confirm the database answers and report its PostGIS version."""
    pool = get_pool()
    async with pool.acquire() as conn:
        postgis_version = await conn.fetchval("SELECT postgis_lib_version()")
    return {"database": "ok", "postgis": postgis_version}
