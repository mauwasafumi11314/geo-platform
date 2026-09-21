# GeoPlatform

[![CI](https://github.com/mauwasafumi11314/geo-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/mauwasafumi11314/geo-platform/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![PostGIS 3.4](https://img.shields.io/badge/PostGIS-3.4-336791)](https://postgis.net/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A full-stack geospatial platform: load spatial files into PostGIS, serve them as
Mapbox Vector Tiles straight from the database, and render them in the browser
with MapLibre.

It is the natural next step after
[GIS-ETL-Tools](https://github.com/mauwasafumi11314/GIS-ETL-Tools) — the same ETL
problem, but with the hardcoded paths and passwords removed, the ArcGIS
dependency replaced by GeoPandas, and an API and web client on the other end.

---

## Architecture

```
  Spatial files                PostgreSQL 16 + PostGIS 3.4                 Browser
┌─────────────────┐          ┌──────────────────────────────┐        ┌────────────────┐
│ .shp  .geojson  │          │ layers    catalogue + bounds │        │ MapLibre GL JS │
│ .gpkg .fgb      │──ETL────▶│ features  geometry + JSONB   │        │ vector tiles   │
│ .kml  .gml      │ GeoPandas│ GiST (layer_id, geom)        │        │ GeoJSON        │
└─────────────────┘  + COPY  └───────────────┬──────────────┘        └───────▲────────┘
                                             │                               │
                                       ST_AsMVT │ ST_AsGeoJSON                │
                                             │                               │
                                  ┌──────────▼───────────┐       HTTP        │
                                  │ FastAPI + asyncpg    │───────────────────┘
                                  │ /tiles  /features    │
                                  └──────────────────────┘
```

Three pieces, each doing one job:

| Component | Stack | Responsibility |
|-----------|-------|----------------|
| **ETL** | GeoPandas, Shapely, psycopg 3 | Read any OGR format, reproject to EPSG:4326, stream rows into PostGIS with `COPY` |
| **API** | FastAPI, asyncpg | Encode tiles with `ST_AsMVT`, serve GeoJSON, expose layer metadata and TileJSON |
| **Web** | MapLibre GL JS, Vite | Discover layers at runtime, render them, show attributes on click |

---

## Quickstart

```bash
git clone https://github.com/mauwasafumi11314/geo-platform.git
cd geo-platform
cp .env.example .env        # then edit POSTGRES_PASSWORD
make up                     # or: docker compose up -d --build
```

| What | Where |
|------|-------|
| Map | <http://localhost:5173> |
| API docs (OpenAPI) | <http://localhost:8000/docs> |
| Health check | <http://localhost:8000/health> |

The database initialises itself from `db/init/`, including two small sample
layers, so the map has something on it before you load anything.

---

## Loading your own data

Drop files into `./data/` and run the loader:

```bash
# Everything under ./data, recursively
make load

# Or directly, with more control
geoplatform-etl load ./data --recursive
geoplatform-etl load ./data/rivers.shp --layer rivers --title "Major rivers" --max-zoom 12
geoplatform-etl load ./data --dry-run      # show what would happen, touch nothing
geoplatform-etl list
geoplatform-etl drop rivers --yes
```

Supported formats: `.shp`, `.geojson`, `.json`, `.gpkg`, `.gml`, `.kml`, `.fgb`,
`.tab` — anything GDAL/OGR reads.

The loader:

* derives a layer slug from the filename (`NE 10m Rivers.shp` → `ne_10m_rivers`),
* reprojects to **EPSG:4326** and flattens Z/M coordinates,
* converts attributes to JSON, turning `NaN`/`NaT` into `null`,
* replaces the layer's features by default, or appends with `--append`,
* refreshes the cached feature count and bounds,
* keeps going if one file in a batch fails, and exits non-zero at the end.

Credentials come from `DATABASE_URL` or `--database-url`. Nothing is read from,
or written into, the source files.

---

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness plus the PostGIS version |
| `GET` | `/api/layers` | Every registered layer, with bounds and feature counts |
| `GET` | `/api/layers/{name}` | One layer's metadata |
| `GET` | `/api/layers/{name}/features` | GeoJSON `FeatureCollection`; `bbox`, `limit`, `offset` |
| `GET` | `/api/layers/{name}/tilejson` | TileJSON 3.0.0 document for MapLibre |
| `GET` | `/api/layers/{name}/tiles/{z}/{x}/{y}.pbf` | Mapbox Vector Tile |
| `GET` | `/docs` | Interactive OpenAPI documentation |

```bash
curl localhost:8000/api/layers | jq '.layers[].name'
curl "localhost:8000/api/layers/sample_cities/features?bbox=139,35,140.5,36.5" | jq
curl -s localhost:8000/api/layers/sample_cities/tiles/0/0/0.pbf --output tile.pbf
```

Tiles return `204 No Content` when a tile is empty or outside the layer's zoom
range, and `404` when the layer or the tile coordinate does not exist.

---

## Local development

```bash
make install          # virtualenv + project with [etl,dev] extras
make api              # uvicorn with autoreload on :8000
make web              # vite dev server on :5173
make test             # pytest
make lint             # ruff check + format --check
make fmt              # ruff format + --fix
make help             # everything else
```

Only the database needs to be containerised while developing:

```bash
docker compose up -d db
export DATABASE_URL=postgresql://geo:change-me@localhost:5432/geoplatform
make api
```

### Testing

The suite exercises the real database — `ST_AsMVT` and `ST_TileEnvelope` have no
meaningful stub. Each test rebuilds the schema from `db/init/` and seeds the
sample layers, so the assertions are pinned to known data.

If no database is reachable, the DB-backed tests **skip** instead of failing, so
`pytest` still works on a machine with nothing running. CI runs them properly
against a `postgis/postgis:16-3.4` service container.

---

## Project layout

```
geo-platform/
├── src/geoplatform/
│   ├── config.py            # environment-driven settings, no hardcoded secrets
│   ├── db.py                # asyncpg pool lifecycle
│   ├── api/
│   │   ├── main.py          # FastAPI app factory and lifespan
│   │   ├── queries.py       # every SQL statement, in one reviewable place
│   │   ├── schemas.py       # Pydantic response models
│   │   ├── deps.py          # shared lookups and bbox parsing
│   │   └── routers/         # layers.py (metadata, GeoJSON) + tiles.py (MVT)
│   └── etl/
│       ├── sources.py       # file discovery and slug/title derivation
│       ├── loader.py        # GeoPandas -> COPY -> PostGIS
│       └── __main__.py      # geoplatform-etl CLI
├── db/init/                 # extensions, schema, sample data (run on first boot)
├── frontend/                # MapLibre client (Vite)
├── docker/                  # separate API and ETL images
├── tests/                   # pytest; DB tests skip when no database is present
└── docs/architecture.md     # design decisions and trade-offs
```

---

## Design notes

**One schema for every dataset.** Rather than creating a physical table per
shapefile, every dataset becomes a row in `layers` and its records become rows
in `features` with attributes in a JSONB column. The API needs no dynamic SQL
and no identifier interpolation, and there is exactly one spatial index to
maintain. The trade-off — attributes are not individually typed columns — is
discussed in [docs/architecture.md](docs/architecture.md).

**Tiles are encoded in the database.** `ST_AsMVT` returns a finished protobuf;
the API hands those bytes to the client without parsing them.

**The spatial index is actually used.** The tile query reprojects the *tile
envelope* into EPSG:4326 and compares it against the stored geometry, rather
than reprojecting the geometry column. `EXPLAIN` confirms an index scan on
`features_layer_geom_idx` instead of a sequential scan.

**Bulk loading uses `COPY`, not `INSERT`.** Geometry travels as hex EWKB, which
PostGIS parses natively from a text COPY stream.

**Nothing is hardcoded.** Connection details come from `DATABASE_URL`; paths are
CLI arguments. `.env` is gitignored, and `.env.example` documents every setting.

---

## Roadmap

- [ ] Raster layers via `postgis_raster` and a `/cog` endpoint
- [ ] Tile caching in front of the API (Redis or a CDN)
- [ ] Attribute-typed tiles: promote common JSONB keys into real MVT fields
- [ ] Authentication and per-layer visibility
- [ ] Draw and edit features from the browser

## License

[MIT](LICENSE) © Masafumi Matsushita
