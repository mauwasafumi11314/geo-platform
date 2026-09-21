"""SQL used by the API.

Kept in one module so the database contract is reviewable in a single place.
Every statement is fully parameterised - no identifier or literal is ever
interpolated into these strings.
"""

from __future__ import annotations

LAYER_COLUMNS = """
    id, name, title, description, geometry_type, srid_source, source_path,
    feature_count, min_zoom, max_zoom,
    bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y,
    created_at, updated_at
"""

LIST_LAYERS = f"SELECT {LAYER_COLUMNS} FROM layers ORDER BY title"

GET_LAYER_BY_NAME = f"SELECT {LAYER_COLUMNS} FROM layers WHERE name = $1"

# Mapbox Vector Tile encoding.
#
# `bounds` produces the tile envelope twice: in Web Mercator for
# ST_AsMVTGeom, and reprojected to EPSG:4326 so the `&&` filter below can use
# the GiST index on features.geom. Transforming the *envelope* rather than the
# *column* is what keeps this query index-backed.
#
# Attributes travel as a single `props` string rather than expanded JSONB
# columns: the generic schema has no fixed attribute list, and serialising once
# here keeps the query static across PostGIS versions. The frontend calls
# JSON.parse on it.
SELECT_TILE = """
WITH bounds AS (
    SELECT ST_TileEnvelope($2::int, $3::int, $4::int) AS mercator,
           ST_Transform(ST_TileEnvelope($2::int, $3::int, $4::int), 4326) AS wgs84
)
SELECT ST_AsMVT(tile, $5::text, $6::int, 'geom', 'id')
FROM (
    SELECT f.id,
           f.properties::text AS props,
           ST_AsMVTGeom(
               ST_Transform(f.geom, 3857),
               bounds.mercator,
               $6::int,
               $7::int,
               true
           ) AS geom
    FROM features f, bounds
    WHERE f.layer_id = $1::int
      AND f.geom && bounds.wgs84
) AS tile
WHERE tile.geom IS NOT NULL
"""

# GeoJSON FeatureCollection, assembled in the database so the API only has to
# hand the resulting object to the JSON encoder.
SELECT_FEATURES = """
SELECT jsonb_build_object(
    'type', 'FeatureCollection',
    'features', COALESCE(
        jsonb_agg(
            jsonb_build_object(
                'type', 'Feature',
                'id', sub.id,
                'geometry', ST_AsGeoJSON(sub.geom)::jsonb,
                'properties', sub.properties
            )
            ORDER BY sub.id
        ),
        '[]'::jsonb
    )
)
FROM (
    SELECT f.id, f.geom, f.properties
    FROM features f
    WHERE f.layer_id = $1::int
      AND (
          $2::double precision IS NULL
          OR f.geom && ST_MakeEnvelope(
              $2::double precision, $3::double precision,
              $4::double precision, $5::double precision, 4326
          )
      )
    ORDER BY f.id
    LIMIT $6::int OFFSET $7::int
) AS sub
"""

COUNT_FEATURES = """
SELECT count(*)
FROM features f
WHERE f.layer_id = $1::int
  AND (
      $2::double precision IS NULL
      OR f.geom && ST_MakeEnvelope(
          $2::double precision, $3::double precision,
          $4::double precision, $5::double precision, 4326
      )
  )
"""
