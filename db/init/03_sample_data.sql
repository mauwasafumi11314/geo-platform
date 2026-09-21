-- Minimal seed data so `docker compose up` produces a map with something on it
-- before you have run the ETL. Safe to delete.

INSERT INTO layers (name, title, description, geometry_type, srid_source, source_path, max_zoom)
VALUES
    ('sample_cities',  'Sample cities',  'A handful of world cities, shipped as seed data.',  'Point',   4326, 'db/init/03_sample_data.sql', 14),
    ('sample_regions', 'Sample regions', 'Two rough bounding regions, shipped as seed data.', 'Polygon', 4326, 'db/init/03_sample_data.sql', 12)
ON CONFLICT (name) DO NOTHING;

INSERT INTO features (layer_id, properties, geom)
SELECT l.id,
       jsonb_build_object('city', raw.city, 'country', raw.country, 'population', raw.population),
       ST_SetSRID(ST_MakePoint(raw.lon::double precision, raw.lat::double precision), 4326)
FROM layers l
CROSS JOIN (VALUES
    ('Tokyo',       'Japan',           139.6917,  35.6895, 37400068),
    ('Delhi',       'India',            77.1025,  28.7041, 28514000),
    ('Shanghai',    'China',           121.4737,  31.2304, 25582000),
    ('Sao Paulo',   'Brazil',          -46.6333, -23.5505, 21650000),
    ('Mexico City', 'Mexico',          -99.1332,  19.4326, 21581000),
    ('Cairo',       'Egypt',            31.2357,  30.0444, 20076000),
    ('New York',    'United States',   -74.0060,  40.7128, 18819000),
    ('Lagos',       'Nigeria',            3.3792,   6.5244, 13904000),
    ('London',      'United Kingdom',   -0.1278,  51.5074,  9046000),
    ('Sydney',      'Australia',       151.2093, -33.8688,  4926000)
) AS raw(city, country, lon, lat, population)
WHERE l.name = 'sample_cities'
  AND NOT EXISTS (SELECT 1 FROM features f WHERE f.layer_id = l.id);

INSERT INTO features (layer_id, properties, geom)
SELECT l.id,
       jsonb_build_object('region', raw.region),
       ST_MakeEnvelope(raw.west::double precision, raw.south::double precision,
                       raw.east::double precision, raw.north::double precision, 4326)
FROM layers l
CROSS JOIN (VALUES
    ('Eastern Asia',   129.0, 30.0, 146.0, 46.0),
    ('Western Europe', -10.0, 41.0,  16.0, 56.0)
) AS raw(region, west, south, east, north)
WHERE l.name = 'sample_regions'
  AND NOT EXISTS (SELECT 1 FROM features f WHERE f.layer_id = l.id);

SELECT refresh_layer_stats(NULL);
