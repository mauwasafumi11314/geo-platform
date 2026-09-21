# ETL image: adds GeoPandas and its GDAL/GEOS/PROJ dependencies. Only needed to
# run `geoplatform-etl`, which is why it is a separate build from the API.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# GeoPandas wheels bundle GDAL, but shapefile encodings and projection lookups
# still want the system PROJ data.
RUN apt-get update \
    && apt-get install --no-install-recommends -y proj-data \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[etl]"

# Mount your data here: docker compose run --rm etl load /data
VOLUME ["/data"]

ENTRYPOINT ["geoplatform-etl"]
CMD ["--help"]
