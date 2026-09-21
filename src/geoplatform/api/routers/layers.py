"""Layer metadata and GeoJSON feature access."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from geoplatform.api.deps import fetch_layer, parse_bbox
from geoplatform.api.queries import COUNT_FEATURES, LIST_LAYERS, SELECT_FEATURES
from geoplatform.api.schemas import FeatureCollection, Layer, LayerList, TileJSON
from geoplatform.config import get_settings
from geoplatform.db import get_pool

router = APIRouter(prefix="/layers", tags=["layers"])


@router.get("", response_model=LayerList, summary="List every registered layer")
async def list_layers() -> LayerList:
    pool = get_pool()
    async with pool.acquire() as conn:
        records = await conn.fetch(LIST_LAYERS)
    layers = [Layer.from_record(record) for record in records]
    return LayerList(layers=layers, count=len(layers))


@router.get("/{name}", response_model=Layer, summary="Describe one layer")
async def get_layer(name: str) -> Layer:
    return Layer.from_record(await fetch_layer(name))


@router.get(
    "/{name}/features",
    response_model=FeatureCollection,
    summary="Fetch features as GeoJSON",
)
async def get_features(
    name: str,
    bbox: str | None = Query(
        default=None,
        description="Spatial filter as west,south,east,north in EPSG:4326",
        examples=["139.0,35.0,140.5,36.5"],
    ),
    limit: int = Query(default=500, ge=1),
    offset: int = Query(default=0, ge=0),
) -> FeatureCollection:
    settings = get_settings()
    limit = min(limit, settings.max_features)
    layer = await fetch_layer(name)
    west, south, east, north = parse_bbox(bbox)

    pool = get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(COUNT_FEATURES, layer["id"], west, south, east, north)
        collection = await conn.fetchval(
            SELECT_FEATURES, layer["id"], west, south, east, north, limit, offset
        )

    return FeatureCollection(
        features=collection["features"],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{name}/tilejson",
    response_model=TileJSON,
    summary="TileJSON document for the layer's vector tiles",
)
async def get_tilejson(name: str, request: Request) -> TileJSON:
    layer = await fetch_layer(name)
    base_url = str(request.base_url).rstrip("/")
    tile_url = f"{base_url}/api/layers/{layer['name']}/tiles/{{z}}/{{x}}/{{y}}.pbf"

    bounds = (
        layer["bbox_min_x"],
        layer["bbox_min_y"],
        layer["bbox_max_x"],
        layer["bbox_max_y"],
    )
    document = TileJSON(
        name=layer["name"],
        description=layer["description"],
        tiles=[tile_url],
        minzoom=layer["min_zoom"],
        maxzoom=layer["max_zoom"],
        vector_layers=[
            {
                "id": layer["name"],
                "description": layer["description"] or layer["title"],
                "minzoom": layer["min_zoom"],
                "maxzoom": layer["max_zoom"],
                # Attributes are carried as one JSON-encoded string; see
                # queries.SELECT_TILE for why.
                "fields": {"props": "String"},
            }
        ],
    )
    if all(b is not None for b in bounds):
        document.bounds = bounds
    return document
