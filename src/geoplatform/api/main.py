"""FastAPI application factory and entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from geoplatform import __version__
from geoplatform.api.routers import layers, tiles
from geoplatform.api.schemas import Health
from geoplatform.config import get_settings
from geoplatform.db import close_pool, create_pool, healthcheck

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
)

DESCRIPTION = """
Vector tile and GeoJSON API over a PostGIS database.

* `GET /api/layers` - every dataset the ETL has loaded
* `GET /api/layers/{name}/tiles/{z}/{x}/{y}.pbf` - Mapbox Vector Tiles, encoded by PostGIS
* `GET /api/layers/{name}/features` - the same data as GeoJSON, with an optional bbox filter
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Own the database pool for the lifetime of the process."""
    await create_pool()
    try:
        yield
    finally:
        await close_pool()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="GeoPlatform API",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET"],
            allow_headers=["*"],
        )

    app.include_router(layers.router, prefix="/api")
    app.include_router(tiles.router, prefix="/api")

    @app.get("/health", response_model=Health, tags=["ops"], summary="Liveness and DB check")
    async def health() -> Health:
        try:
            result = await healthcheck()
        except Exception:  # noqa: BLE001 - health must never raise
            logging.getLogger(__name__).exception("health check failed")
            return Health(status="degraded", version=__version__, database="unavailable")
        return Health(
            status="ok",
            version=__version__,
            database=result["database"],
            postgis=result["postgis"],
        )

    return app


app = create_app()
