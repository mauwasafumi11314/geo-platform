"""Load spatial files into the PostGIS `layers` / `features` tables.

Design notes
------------
* Reading is delegated to GeoPandas, so anything GDAL/OGR understands works -
  shapefiles, GeoJSON, GeoPackage, FlatGeobuf, KML.
* Everything is reprojected to EPSG:4326 on the way in. One storage CRS keeps
  the tile query simple and the spatial index meaningful.
* Rows are streamed with ``COPY``, not ``INSERT``, because a national dataset
  is millions of rows and executemany is an order of magnitude slower.
* Geometry crosses the wire as hex EWKB, which PostGIS parses natively from a
  text COPY stream - no server-side ST_GeomFromText parsing of huge WKT.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import psycopg
from shapely.wkb import dumps as wkb_dumps

from geoplatform.etl.sources import layer_name_for, title_for

logger = logging.getLogger(__name__)

STORAGE_SRID = 4326

UPSERT_LAYER = """
INSERT INTO layers (
    name, title, description, geometry_type, srid_source, source_path, min_zoom, max_zoom
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (name) DO UPDATE SET
    title         = EXCLUDED.title,
    description   = COALESCE(EXCLUDED.description, layers.description),
    geometry_type = EXCLUDED.geometry_type,
    srid_source   = EXCLUDED.srid_source,
    source_path   = EXCLUDED.source_path,
    min_zoom      = EXCLUDED.min_zoom,
    max_zoom      = EXCLUDED.max_zoom
RETURNING id
"""

DELETE_FEATURES = "DELETE FROM features WHERE layer_id = %s"
COPY_FEATURES = "COPY features (layer_id, properties, geom) FROM STDIN"
REFRESH_STATS = "SELECT refresh_layer_stats(%s)"
SELECT_LAYER_STATS = """
SELECT feature_count, bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y
FROM layers WHERE id = %s
"""


@dataclass
class LoadResult:
    """What one file's load actually did."""

    source: Path
    layer_name: str
    title: str
    features_written: int
    features_skipped: int
    source_srid: int | None
    geometry_type: str | None
    replaced: bool
    bbox: tuple[float, float, float, float] | None = None
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        action = "replaced" if self.replaced else "appended to"
        skipped = f", {self.features_skipped} skipped" if self.features_skipped else ""
        return (
            f"{self.source.name} -> {action} layer '{self.layer_name}': "
            f"{self.features_written} features{skipped}"
        )


def _json_safe(value: Any) -> Any:
    """Coerce a pandas/numpy cell into something json.dumps can handle."""
    # Covers None, NaN, NaT and pandas' NA in one go. pd.isna raises on
    # array-likes, which is why this is guarded.
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        # Binary blobs have no place in tile attributes.
        return None
    if hasattr(value, "item"):
        # numpy scalars expose .item() to unwrap to a Python builtin.
        try:
            return _json_safe(value.item())
        except (ValueError, AttributeError):
            pass
    return str(value)


def _properties(row: dict[str, Any], geometry_column: str) -> dict[str, Any]:
    return {str(key): _json_safe(value) for key, value in row.items() if key != geometry_column}


def read_dataset(
    path: Path,
    *,
    assume_srid: int = STORAGE_SRID,
    fix_geometry: bool = False,
) -> tuple[gpd.GeoDataFrame, int | None, list[str]]:
    """Read a file and return it reprojected to EPSG:4326.

    Returns the frame, the SRID it arrived in (None when the file carried no
    CRS), and any warnings worth showing the operator.
    """
    warnings: list[str] = []
    gdf = gpd.read_file(path)

    if gdf.empty:
        warnings.append(f"{path.name} contains no features")

    source_srid: int | None = None
    if gdf.crs is None:
        warnings.append(
            f"{path.name} has no CRS; assuming EPSG:{assume_srid}. "
            "Pass --assume-srid if that is wrong."
        )
        gdf = gdf.set_crs(epsg=assume_srid)
        source_srid = assume_srid
    else:
        source_srid = gdf.crs.to_epsg()

    if source_srid != STORAGE_SRID:
        gdf = gdf.to_crs(epsg=STORAGE_SRID)

    # The features table is typed geometry(Geometry, 4326), which rejects Z/M
    # coordinates - and vector tiles are 2D regardless.
    if not gdf.empty and gdf.geometry.has_z.any():
        warnings.append(f"{path.name} has 3D geometry; flattening to 2D")
        gdf = gdf.set_geometry(gdf.geometry.force_2d())

    if fix_geometry and not gdf.empty:
        invalid = int((~gdf.geometry.is_valid).sum())
        if invalid:
            warnings.append(f"{path.name}: repairing {invalid} invalid geometries")
            gdf = gdf.set_geometry(gdf.geometry.make_valid())

    return gdf, source_srid, warnings


def load_dataset(
    conn: psycopg.Connection,
    path: Path,
    *,
    layer_name: str | None = None,
    title: str | None = None,
    description: str | None = None,
    replace: bool = True,
    min_zoom: int = 0,
    max_zoom: int = 14,
    assume_srid: int = STORAGE_SRID,
    fix_geometry: bool = False,
) -> LoadResult:
    """Load one file into the database inside a single transaction."""
    name = layer_name or layer_name_for(path)
    display_title = title or title_for(path)

    gdf, source_srid, warnings = read_dataset(
        path, assume_srid=assume_srid, fix_geometry=fix_geometry
    )

    geometry_column = gdf.geometry.name
    geometry_type = None
    if not gdf.empty:
        types = gdf.geom_type.dropna().unique().tolist()
        geometry_type = types[0] if len(types) == 1 else "Geometry"

    written = 0
    skipped = 0

    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            UPSERT_LAYER,
            (
                name,
                display_title,
                description,
                geometry_type,
                source_srid,
                str(path),
                min_zoom,
                max_zoom,
            ),
        )
        row = cur.fetchone()
        if row is None:  # pragma: no cover - RETURNING id always yields a row
            raise RuntimeError(f"Failed to register layer {name!r}")
        layer_id = row[0]

        if replace:
            cur.execute(DELETE_FEATURES, (layer_id,))

        with cur.copy(COPY_FEATURES) as copy:
            for record in gdf.to_dict(orient="records"):
                geometry = record.get(geometry_column)
                if geometry is None or geometry.is_empty:
                    skipped += 1
                    continue
                properties = _properties(record, geometry_column)
                copy.write_row(
                    (
                        layer_id,
                        json.dumps(properties, ensure_ascii=False),
                        wkb_dumps(geometry, hex=True, srid=STORAGE_SRID),
                    )
                )
                written += 1

        cur.execute(REFRESH_STATS, (layer_id,))
        cur.execute(SELECT_LAYER_STATS, (layer_id,))
        stats = cur.fetchone()

    bbox = None
    if stats and all(value is not None for value in stats[1:]):
        bbox = (stats[1], stats[2], stats[3], stats[4])

    if skipped:
        warnings.append(f"{path.name}: skipped {skipped} null or empty geometries")

    result = LoadResult(
        source=path,
        layer_name=name,
        title=display_title,
        features_written=written,
        features_skipped=skipped,
        source_srid=source_srid,
        geometry_type=geometry_type,
        replaced=replace,
        bbox=bbox,
        warnings=warnings,
    )
    logger.info("%s", result.summary())
    for warning in warnings:
        logger.warning("%s", warning)
    return result
