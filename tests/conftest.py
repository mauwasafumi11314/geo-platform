"""Test fixtures.

The suite talks to a real PostGIS instance - ST_AsMVT and ST_TileEnvelope have
no meaningful stub. When no database is reachable the whole suite skips rather
than failing, so `pytest` still works on a laptop with nothing running.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from geoplatform.config import DEFAULT_DATABASE_URL, get_settings, normalise_dsn
from geoplatform.db import close_pool, create_pool

ROOT = Path(__file__).resolve().parents[1]
INIT_SQL = sorted((ROOT / "db" / "init").glob("*.sql"))


def _safe_target(dsn: str) -> str:
    """Host/db portion of a DSN, with any credentials removed."""
    return dsn.rsplit("@", 1)[-1]


@pytest.fixture(scope="session")
def dsn() -> str:
    url = normalise_dsn(os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL))

    async def probe() -> None:
        conn = await asyncpg.connect(url, timeout=5)
        try:
            await conn.fetchval("SELECT postgis_lib_version()")
        finally:
            await conn.close()

    try:
        asyncio.run(probe())
    except Exception as exc:  # noqa: BLE001 - any failure means "no database"
        pytest.skip(f"PostGIS not reachable at {_safe_target(url)}: {type(exc).__name__}")
    return url


@pytest.fixture
def configured_env(dsn: str, monkeypatch: pytest.MonkeyPatch):
    """Point the application at the test database and reset the cached settings."""
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("TILE_CACHE_SECONDS", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def db(dsn: str):
    """A connection to a freshly rebuilt schema, seeded with the sample data."""
    conn = await asyncpg.connect(dsn)
    await conn.execute("DROP TABLE IF EXISTS features CASCADE")
    await conn.execute("DROP TABLE IF EXISTS layers CASCADE")
    for script in INIT_SQL:
        await conn.execute(script.read_text(encoding="utf-8"))
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def client(db, configured_env):
    """An HTTP client bound to the app.

    ASGITransport does not run lifespan handlers, so the pool is opened and
    closed here instead.
    """
    from geoplatform.api.main import create_app

    await create_pool()
    app = create_app()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as http_client:
            yield http_client
    finally:
        await close_pool()
