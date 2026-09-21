-- Core schema.
--
-- The platform uses a generic two-table model rather than one physical table
-- per dataset. Every uploaded dataset becomes a row in `layers`, and its
-- records become rows in `features` with their attributes kept in a JSONB
-- column. That keeps the API and the tile query completely static: no
-- dynamic SQL, no identifier interpolation, one GiST index to maintain.

CREATE TABLE IF NOT EXISTS layers (
    id             SERIAL PRIMARY KEY,
    -- URL-safe slug, used as the MVT source-layer name
    name           TEXT NOT NULL UNIQUE CHECK (name ~ '^[a-z0-9][a-z0-9_]*$'),
    title          TEXT NOT NULL,
    description    TEXT,
    -- Dominant OGC geometry type, e.g. Point / LineString / Polygon
    geometry_type  TEXT,
    -- SRID the data arrived in, before it was normalised to EPSG:4326
    srid_source    INTEGER,
    source_path    TEXT,
    feature_count  INTEGER NOT NULL DEFAULT 0 CHECK (feature_count >= 0),
    min_zoom       SMALLINT NOT NULL DEFAULT 0  CHECK (min_zoom BETWEEN 0 AND 22),
    max_zoom       SMALLINT NOT NULL DEFAULT 14 CHECK (max_zoom BETWEEN 0 AND 22),
    -- Cached bounds in EPSG:4326, written by the ETL so /api/layers stays cheap.
    -- Stored as four ordinates instead of a polygon because a single-point
    -- layer produces a degenerate envelope that no polygon typmod accepts.
    bbox_min_x     DOUBLE PRECISION,
    bbox_min_y     DOUBLE PRECISION,
    bbox_max_x     DOUBLE PRECISION,
    bbox_max_y     DOUBLE PRECISION,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT layers_zoom_range CHECK (max_zoom >= min_zoom)
);

CREATE TABLE IF NOT EXISTS features (
    id         BIGSERIAL PRIMARY KEY,
    layer_id   INTEGER NOT NULL REFERENCES layers (id) ON DELETE CASCADE,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- All geometry is normalised to EPSG:4326 on ingest. The tile endpoint
    -- reprojects to EPSG:3857 on read, which keeps storage canonical.
    geom       geometry(Geometry, 4326) NOT NULL
);

-- Spatial index: the tile query filters with `geom && <tile envelope>` in
-- EPSG:4326 so this index is actually usable (transforming the column instead
-- of the envelope would force a sequential scan).
CREATE INDEX IF NOT EXISTS features_geom_idx ON features USING GIST (geom);

-- Composite index matching the tile query's real predicate,
-- `layer_id = ? AND geom && ?`. The integer column only works inside a GiST
-- index because btree_gist is installed (see 01_extensions.sql).
CREATE INDEX IF NOT EXISTS features_layer_geom_idx ON features USING GIST (layer_id, geom);

-- Plain btree for the non-spatial paths: cascade deletes, feature counts,
-- and the loader's "replace this layer" DELETE.
CREATE INDEX IF NOT EXISTS features_layer_id_idx ON features (layer_id);

-- Attribute lookups inside the JSONB payload.
CREATE INDEX IF NOT EXISTS features_properties_idx ON features USING GIN (properties);

-- Keep layers.updated_at honest without relying on application code.
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS layers_set_updated_at ON layers;
CREATE TRIGGER layers_set_updated_at
    BEFORE UPDATE ON layers
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- Recompute cached statistics for one layer (or all layers when given NULL).
CREATE OR REPLACE FUNCTION refresh_layer_stats(target_layer_id INTEGER DEFAULT NULL)
RETURNS void AS $$
BEGIN
    UPDATE layers l
    SET feature_count = COALESCE(s.cnt, 0),
        bbox_min_x    = ST_XMin(s.ext),
        bbox_min_y    = ST_YMin(s.ext),
        bbox_max_x    = ST_XMax(s.ext),
        bbox_max_y    = ST_YMax(s.ext)
    FROM (
        SELECT f.layer_id, count(*) AS cnt, ST_Extent(f.geom) AS ext
        FROM features f
        WHERE target_layer_id IS NULL OR f.layer_id = target_layer_id
        GROUP BY f.layer_id
    ) s
    WHERE l.id = s.layer_id
      AND (target_layer_id IS NULL OR l.id = target_layer_id);

    -- Layers that lost every feature need zeroing out too.
    UPDATE layers l
    SET feature_count = 0,
        bbox_min_x = NULL, bbox_min_y = NULL,
        bbox_max_x = NULL, bbox_max_y = NULL
    WHERE (target_layer_id IS NULL OR l.id = target_layer_id)
      AND NOT EXISTS (SELECT 1 FROM features f WHERE f.layer_id = l.id);
END;
$$ LANGUAGE plpgsql;
