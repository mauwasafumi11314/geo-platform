"""Shared helpers for the routers."""

from __future__ import annotations

import asyncpg
from fastapi import HTTPException, status

from geoplatform.api.queries import GET_LAYER_BY_NAME
from geoplatform.api.schemas import BBox
from geoplatform.db import get_pool

# Starlette renamed HTTP_422_UNPROCESSABLE_ENTITY and deprecated the old name;
# the numeric code is stable across both.
HTTP_422_UNPROCESSABLE = 422

NO_BBOX: tuple[None, None, None, None] = (None, None, None, None)


async def fetch_layer(name: str) -> asyncpg.Record:
    """Look a layer up by slug, or raise 404."""
    pool = get_pool()
    async with pool.acquire() as conn:
        record = await conn.fetchrow(GET_LAYER_BY_NAME, name)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Layer {name!r} not found",
        )
    return record


def parse_bbox(raw: str | None) -> BBox | tuple[None, None, None, None]:
    """Parse a ``west,south,east,north`` query parameter.

    Returns a tuple of Nones when no bbox was supplied, which the SQL treats as
    "no spatial filter".
    """
    if raw is None or raw.strip() == "":
        return NO_BBOX

    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 4:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail="bbox must have four comma-separated values: west,south,east,north",
        )
    try:
        west, south, east, north = (float(p) for p in parts)
    except ValueError:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail="bbox values must be numbers",
        ) from None

    if west > east or south > north:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail="bbox must be ordered west,south,east,north",
        )
    return west, south, east, north
