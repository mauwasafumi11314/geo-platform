"""End-to-end API tests against a live PostGIS instance.

Every test runs on the schema in db/init, seeded with the sample layers, so the
expected numbers below come from db/init/03_sample_data.sql.
"""

from __future__ import annotations

from httpx import AsyncClient

MVT_MEDIA_TYPE = "application/vnd.mapbox-vector-tile"
SAMPLE_CITY_COUNT = 10


async def test_health_reports_postgis(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["postgis"]


async def test_list_layers_includes_seeded_layers(client: AsyncClient) -> None:
    response = await client.get("/api/layers")
    assert response.status_code == 200
    body = response.json()

    names = {layer["name"] for layer in body["layers"]}
    assert {"sample_cities", "sample_regions"} <= names
    assert body["count"] == len(body["layers"])


async def test_layer_detail_carries_cached_statistics(client: AsyncClient) -> None:
    response = await client.get("/api/layers/sample_cities")
    assert response.status_code == 200
    layer = response.json()

    assert layer["geometry_type"] == "Point"
    assert layer["feature_count"] == SAMPLE_CITY_COUNT
    # refresh_layer_stats() should have populated the bounds on seed.
    west, south, east, north = layer["bbox"]
    assert -180 <= west < east <= 180
    assert -90 <= south < north <= 90


async def test_unknown_layer_is_404(client: AsyncClient) -> None:
    response = await client.get("/api/layers/does_not_exist")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


async def test_features_are_valid_geojson(client: AsyncClient) -> None:
    response = await client.get("/api/layers/sample_cities/features")
    assert response.status_code == 200
    body = response.json()

    assert body["type"] == "FeatureCollection"
    assert body["total"] == SAMPLE_CITY_COUNT
    assert len(body["features"]) == SAMPLE_CITY_COUNT

    feature = body["features"][0]
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Point"
    assert len(feature["geometry"]["coordinates"]) == 2
    assert "city" in feature["properties"]


async def test_features_bbox_filter_narrows_results(client: AsyncClient) -> None:
    # A tight box around Tokyo (139.6917, 35.6895).
    response = await client.get(
        "/api/layers/sample_cities/features", params={"bbox": "139,35,140.5,36.5"}
    )
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 1
    assert body["features"][0]["properties"]["city"] == "Tokyo"


async def test_features_paging(client: AsyncClient) -> None:
    first = await client.get("/api/layers/sample_cities/features", params={"limit": 3})
    second = await client.get(
        "/api/layers/sample_cities/features", params={"limit": 3, "offset": 3}
    )

    assert first.json()["total"] == SAMPLE_CITY_COUNT
    assert len(first.json()["features"]) == 3
    assert len(second.json()["features"]) == 3

    first_ids = {f["id"] for f in first.json()["features"]}
    second_ids = {f["id"] for f in second.json()["features"]}
    assert first_ids.isdisjoint(second_ids)


async def test_malformed_bbox_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/layers/sample_cities/features", params={"bbox": "1,2,3"})
    assert response.status_code == 422


async def test_tilejson_describes_the_tile_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/layers/sample_cities/tilejson")
    assert response.status_code == 200
    document = response.json()

    assert document["tilejson"] == "3.0.0"
    assert document["tiles"] == ["http://testserver/api/layers/sample_cities/tiles/{z}/{x}/{y}.pbf"]
    assert document["vector_layers"][0]["id"] == "sample_cities"


async def test_world_tile_contains_encoded_features(client: AsyncClient) -> None:
    response = await client.get("/api/layers/sample_cities/tiles/0/0/0.pbf")
    assert response.status_code == 200
    assert response.headers["content-type"] == MVT_MEDIA_TYPE
    # ST_AsMVT returns a non-empty protobuf when any feature intersects the tile.
    assert len(response.content) > 0


async def test_tile_with_no_features_is_204(client: AsyncClient) -> None:
    # Zoom 8 over the middle of the Pacific: inside the grid, no sample cities.
    response = await client.get("/api/layers/sample_cities/tiles/8/40/120.pbf")
    assert response.status_code == 204
    assert response.content == b""


async def test_tile_above_max_zoom_is_204(client: AsyncClient) -> None:
    # sample_cities is registered with max_zoom 14.
    response = await client.get("/api/layers/sample_cities/tiles/16/0/0.pbf")
    assert response.status_code == 204


async def test_tile_outside_the_grid_is_404(client: AsyncClient) -> None:
    # Zoom 1 has a 2x2 grid, so x=5 cannot exist.
    response = await client.get("/api/layers/sample_cities/tiles/1/5/0.pbf")
    assert response.status_code == 404
    assert "tile grid" in response.json()["detail"]


async def test_tile_zoom_out_of_range_is_422(client: AsyncClient) -> None:
    response = await client.get("/api/layers/sample_cities/tiles/40/0/0.pbf")
    assert response.status_code == 422


async def test_tile_for_unknown_layer_is_404(client: AsyncClient) -> None:
    response = await client.get("/api/layers/nope/tiles/0/0/0.pbf")
    assert response.status_code == 404


async def test_openapi_schema_is_served(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/layers" in paths
    assert "/api/layers/{name}/tiles/{z}/{x}/{y}.pbf" in paths
