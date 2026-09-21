"""Response models.

These are the public shape of the API; the database schema is free to change
underneath them as long as the mapping in ``from_record`` is updated.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# GeoJSON orders bounds as [west, south, east, north].
BBox = tuple[float, float, float, float]


class Layer(BaseModel):
    """A dataset registered in the platform."""

    id: int
    name: str = Field(description="URL-safe slug, also the MVT source-layer name")
    title: str
    description: str | None = None
    geometry_type: str | None = None
    srid_source: int | None = Field(
        default=None, description="SRID of the source file before normalisation to 4326"
    )
    feature_count: int
    min_zoom: int
    max_zoom: int
    bbox: BBox | None = Field(default=None, description="[west, south, east, north] in EPSG:4326")
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: Any) -> Layer:
        bounds = (
            record["bbox_min_x"],
            record["bbox_min_y"],
            record["bbox_max_x"],
            record["bbox_max_y"],
        )
        return cls(
            id=record["id"],
            name=record["name"],
            title=record["title"],
            description=record["description"],
            geometry_type=record["geometry_type"],
            srid_source=record["srid_source"],
            feature_count=record["feature_count"],
            min_zoom=record["min_zoom"],
            max_zoom=record["max_zoom"],
            bbox=bounds if all(b is not None for b in bounds) else None,
            created_at=record["created_at"],
            updated_at=record["updated_at"],
        )


class LayerList(BaseModel):
    layers: list[Layer]
    count: int


class FeatureCollection(BaseModel):
    """A GeoJSON FeatureCollection plus paging metadata."""

    type: str = "FeatureCollection"
    features: list[dict[str, Any]]
    total: int = Field(description="Features matching the query, ignoring limit/offset")
    limit: int
    offset: int


class TileJSON(BaseModel):
    """Subset of the TileJSON 3.0.0 spec that MapLibre needs."""

    tilejson: str = "3.0.0"
    name: str
    description: str | None = None
    scheme: str = "xyz"
    tiles: list[str]
    minzoom: int
    maxzoom: int
    bounds: BBox = (-180.0, -85.05112878, 180.0, 85.05112878)
    vector_layers: list[dict[str, Any]]


class Health(BaseModel):
    status: str
    version: str
    database: str
    postgis: str | None = None
