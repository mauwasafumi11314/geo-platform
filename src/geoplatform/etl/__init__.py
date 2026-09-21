"""ETL: read spatial files with GeoPandas, normalise them, load them into PostGIS.

``loader`` is deliberately not imported here - it pulls in the heavy geo stack
(GeoPandas, Shapely, psycopg) that the API image does not install.
"""

__all__ = ["sources"]
