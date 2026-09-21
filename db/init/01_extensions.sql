-- Extensions required by the platform.
--
-- postgis    : geometry type, spatial indexing, ST_AsMVT tile encoding
-- btree_gist : lets a GiST index mix a scalar column with a geometry column,
--              which is what makes the composite (layer_id, geom) index in
--              02_schema.sql possible. Without it PostgreSQL rejects the index
--              with "data type integer has no default operator class".
-- pg_trgm    : fuzzy matching on layer names and text attributes
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
