"""Mapbox Vector Tile endpoint.

Tiles are encoded by PostGIS with ST_AsMVT and returned as raw bytes - the
API never parses or rewrites the protobuf.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Response, status

from geoplatform.api.deps import fetch_layer
from geoplatform.api.queries import SELECT_TILE
from geoplatform.config import get_settings
from geoplatform.db import get_pool

router = APIRouter(prefix="/layers", tags=["tiles"])

MVT_MEDIA_TYPE = "application/vnd.mapbox-vector-tile"
MAX_ZOOM = 22


@router.get(
    "/{name}/tiles/{z}/{x}/{y}.pbf",
    summary="Vector tile for a layer",
    response_class=Response,
    responses={
        200: {"content": {MVT_MEDIA_TYPE: {}}, "description": "Encoded vector tile"},
        204: {"description": "Tile is empty or outside the layer's zoom range"},
        404: {"description": "Unknown layer, or tile coordinates outside the zoom level"},
    },
)
async def get_tile(
    name: str,
    z: int = Path(ge=0, le=MAX_ZOOM, description="Zoom level"),
    x: int = Path(ge=0, description="Tile column"),
    y: int = Path(ge=0, description="Tile row"),
) -> Response:
    # At zoom z the grid is 2^z tiles wide; anything beyond that does not exist.
    grid_size = 1 << z
    if x >= grid_size or y >= grid_size:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tile {z}/{x}/{y} is outside the 2^{z} tile grid",
        )

    settings = get_settings()
    layer = await fetch_layer(name)

    if z < layer["min_zoom"] or z > layer["max_zoom"]:
        return _empty_tile(settings.tile_cache_seconds)

    pool = get_pool()
    async with pool.acquire() as conn:
        tile = await conn.fetchval(
            SELECT_TILE,
            layer["id"],
            z,
            x,
            y,
            layer["name"],
            settings.tile_extent,
            settings.tile_buffer,
        )

    if not tile:
        return _empty_tile(settings.tile_cache_seconds)

    return Response(
        content=bytes(tile),
        media_type=MVT_MEDIA_TYPE,
        headers=_cache_headers(settings.tile_cache_seconds),
    )


def _empty_tile(cache_seconds: int) -> Response:
    """204 tells MapLibre "nothing here" without it treating the tile as an error."""
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=_cache_headers(cache_seconds))


def _cache_headers(cache_seconds: int) -> dict[str, str]:
    if cache_seconds <= 0:
        return {"Cache-Control": "no-store"}
    return {"Cache-Control": f"public, max-age={cache_seconds}"}
