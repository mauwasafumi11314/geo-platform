# Architecture and design decisions

This document records the choices that are not obvious from the code, and the
trade-offs each one accepted.

## 1. One generic schema, not a table per dataset

The obvious design — and the one the predecessor project
[GIS-ETL-Tools](https://github.com/mauwasafumi11314/GIS-ETL-Tools) used, via
`shp2pgsql` — gives every shapefile its own physical table. That produces nicely
typed attribute columns, but it forces every downstream query to be built by
string concatenation around a table name.

This project stores a catalogue instead:

```
layers    (id, name, title, geometry_type, feature_count, bbox_*, min/max_zoom, …)
features  (id, layer_id → layers.id, properties JSONB, geom geometry(Geometry, 4326))
```

**Gained**

* Every SQL statement in `api/queries.py` is static and fully parameterised.
  There is no dynamic identifier interpolation anywhere, so there is no SQL
  injection surface in the tile path.
* One GiST index to maintain, one schema to migrate.
* Adding a dataset is an `INSERT`, not a DDL migration.

**Given up**

* Attributes are not individually typed columns, so `WHERE population > 1000000`
  becomes `WHERE (properties->>'population')::numeric > 1000000`. The GIN index
  on `properties` keeps containment queries fast, but range queries on a single
  key are slower than a real column would be.
* Vector tile attributes arrive as one JSON string rather than typed fields
  (see §3).

For a platform whose job is "serve arbitrary uploaded datasets", that trade is
worth it. For a fixed, known set of layers with heavy attribute querying, a
table per layer would be the better call.

## 2. EPSG:4326 in storage, EPSG:3857 on read

Everything is reprojected to WGS84 on ingest. Tiles are Web Mercator, so the
tile endpoint transforms on the way out.

The important detail is *which side of the comparison gets transformed*:

```sql
WHERE f.geom && ST_Transform(ST_TileEnvelope(z, x, y), 4326)   -- index usable
```

not

```sql
WHERE ST_Transform(f.geom, 3857) && ST_TileEnvelope(z, x, y)   -- sequential scan
```

Transforming the column makes the expression non-indexable and forces a scan of
every row in the table. Transforming the *envelope* leaves `f.geom` bare, so
PostgreSQL can use the GiST index. `EXPLAIN` on the tile predicate confirms an
`Index Scan using features_layer_geom_idx`.

Storing geometry pre-projected in 3857 would skip the per-tile transform
entirely, at the cost of a non-canonical storage CRS and a reprojection on every
GeoJSON response instead. Given that tiles are cacheable and GeoJSON requests
are not, canonical 4326 storage is the better default.

## 3. Tile attributes travel as a JSON string

`ST_AsMVT` builds tile attributes from the columns of the row type it is given.
With a JSONB attribute bag there is no fixed column list to hand it, and
expanding JSONB into columns would require dynamic SQL — exactly what §1 set out
to avoid.

So the tile query emits one attribute:

```sql
SELECT f.id, f.properties::text AS props, ST_AsMVTGeom(...) AS geom
```

and the client parses it:

```js
const properties = JSON.parse(feature.properties.props ?? '{}');
```

**Cost:** style expressions cannot filter on individual attributes
(`['get', 'population']` sees nothing), so data-driven styling has to be done
from GeoJSON or by promoting keys to real columns.

**Planned fix:** let a layer declare which keys are "promoted", materialise those
as typed columns on `features`, and add them to the `ST_AsMVT` row type. That
keeps the generic case working while giving hot layers real tile fields.

## 4. `COPY` instead of `INSERT`, hex EWKB instead of WKT

The loader streams rows through a single `COPY features (...) FROM STDIN`.
Geometry is serialised client-side with
`shapely.wkb.dumps(geom, hex=True, srid=4326)`, which PostGIS parses natively
from a text COPY stream.

The alternatives are worse: `executemany` pays per-statement overhead on every
row, and sending WKT makes the server re-parse a long text representation of
every coordinate.

Each file loads inside one transaction, so a failure halfway through leaves the
previous version of the layer intact.

## 5. Cached layer statistics

`layers.feature_count` and `bbox_min_x … bbox_max_y` are denormalised copies of
what `count(*)` and `ST_Extent()` would return. `GET /api/layers` is called on
every page load, and running an aggregate over every feature table on each call
does not scale.

`refresh_layer_stats(layer_id)` recomputes them; the loader calls it at the end
of each load. Anything that writes to `features` outside the loader must call it
too, or the catalogue will drift.

Bounds are stored as four `double precision` columns rather than a
`geometry(Polygon, 4326)`. A single-point layer produces a degenerate envelope
that is a `POINT`, not a `POLYGON`, which the polygon typmod rejects.

## 6. Why raw asyncpg rather than an ORM

Every query here is hand-written SQL built around PostGIS functions — `ST_AsMVT`,
`ST_AsMVTGeom`, `ST_TileEnvelope`, `ST_AsGeoJSON`. An ORM would be a layer to
work around rather than a layer to work with, and the tile endpoint returns
`bytes` straight from the database with no row mapping at all.

The cost is that the SQL is the schema contract: `api/queries.py` and
`db/init/02_schema.sql` have to be kept in step by hand. Keeping every statement
in one module is what makes that reviewable.

## 7. Two Docker images

`docker/api.Dockerfile` installs only FastAPI, uvicorn and asyncpg.
`docker/etl.Dockerfile` adds GeoPandas and its GDAL/GEOS/PROJ stack.

The geo stack is large, and the service that answers tile requests never needs
to read a shapefile. Splitting them keeps the API image small and its attack
surface narrow. The ETL runs under the `tools` compose profile, so it is not
started by `docker compose up`.

## 8. Known rough edges

* **Integer attributes can become floats.** GeoPandas loads a column containing
  nulls as `float64`, so `66680` round-trips as `66680.0`. Coercing integral
  floats back to integers would silently change genuinely-float columns, so the
  loader leaves pandas' typing alone.
* **No tile cache.** Every tile request hits PostGIS. `Cache-Control` is set, so
  a CDN or reverse proxy in front of the API is the intended fix.
* **Z/M coordinates are dropped.** The `features` table is typed
  `geometry(Geometry, 4326)`, which rejects 3D geometry, and vector tiles are 2D
  regardless. The loader flattens and warns.
* **`refresh_layer_stats` is O(features)** for the layer it touches. On very
  large layers, loading becomes dominated by the final aggregate.
