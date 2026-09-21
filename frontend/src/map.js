/**
 * Map construction and layer wiring.
 *
 * Each GeoPlatform layer becomes one MapLibre vector source pointed at its
 * TileJSON document, plus one render layer chosen from the layer's geometry
 * type. Attributes arrive as a single JSON string in the `props` field (see
 * the note in geoplatform/api/queries.py), so they are parsed on click.
 */
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

const OSM_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

/** A keyless raster basemap, so the project runs with no API tokens. */
const BASE_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
      attribution: OSM_ATTRIBUTION,
    },
  },
  layers: [{ id: 'basemap', type: 'raster', source: 'osm' }],
};

const PALETTE = ['#4aa8ff', '#ffb454', '#7ddf64', '#ff7b9c', '#c084fc', '#37d4c8'];

export function createMap(container) {
  const map = new maplibregl.Map({
    container,
    style: BASE_STYLE,
    center: [10, 25],
    zoom: 1.4,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), 'top-right');
  map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: 'metric' }));
  return map;
}

function sourceId(layer) {
  return `gp-src-${layer.name}`;
}

/**
 * Resolve a TileJSON tile template against the current origin.
 *
 * The API returns tile URLs relative (`/api/layers/x/tiles/{z}/{x}/{y}.pbf`)
 * so they survive any proxy in front of it. MapLibre, though, requires
 * absolute URLs in a source's `tiles` array - handed a relative one it fetches
 * nothing at all, silently.
 *
 * This is deliberately string concatenation rather than `new URL()`: the URL
 * parser percent-encodes `{` and `}`, which would turn the `{z}/{x}/{y}`
 * placeholders into `%7Bz%7D/...` and break tile addressing.
 */
function absoluteTileURL(template) {
  if (/^[a-z]+:\/\//i.test(template)) return template;
  const path = template.startsWith('/') ? template : `/${template}`;
  return `${window.location.origin}${path}`;
}

export function renderLayerId(layer) {
  return `gp-layer-${layer.name}`;
}

/** Build the MapLibre paint/type spec appropriate to the layer's geometry. */
function renderSpec(layer, color) {
  const base = { id: renderLayerId(layer), source: sourceId(layer), 'source-layer': layer.name };
  const geometry = (layer.geometry_type || '').toLowerCase();

  if (geometry.includes('point')) {
    return {
      ...base,
      type: 'circle',
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 3, 10, 7],
        'circle-color': color,
        'circle-stroke-width': 1,
        'circle-stroke-color': '#0e1318',
        'circle-opacity': 0.9,
      },
    };
  }

  if (geometry.includes('line')) {
    return {
      ...base,
      type: 'line',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': color, 'line-width': ['interpolate', ['linear'], ['zoom'], 4, 0.8, 14, 2.5] },
    };
  }

  // Polygons, and anything mixed, render as a translucent fill with an outline.
  return {
    ...base,
    type: 'fill',
    paint: { 'fill-color': color, 'fill-opacity': 0.35, 'fill-outline-color': color },
  };
}

/**
 * Add a layer to the map, hidden by default.
 * Returns the render layer id so the caller can toggle it.
 */
export function addLayer(map, layer, tilejson, index) {
  const id = sourceId(layer);
  if (!map.getSource(id)) {
    map.addSource(id, {
      type: 'vector',
      tiles: tilejson.tiles.map(absoluteTileURL),
      minzoom: tilejson.minzoom,
      maxzoom: tilejson.maxzoom,
      bounds: tilejson.bounds,
      attribution: 'GeoPlatform',
    });
  }

  const spec = renderSpec(layer, PALETTE[index % PALETTE.length]);
  if (!map.getLayer(spec.id)) {
    map.addLayer({ ...spec, layout: { ...(spec.layout || {}), visibility: 'none' } });
    attachPopup(map, spec.id, layer);
  }
  return spec.id;
}

export function setLayerVisible(map, renderId, visible) {
  if (map.getLayer(renderId)) {
    map.setLayoutProperty(renderId, 'visibility', visible ? 'visible' : 'none');
  }
}

export function fitToLayer(map, layer) {
  if (!layer.bbox) return;
  const [west, south, east, north] = layer.bbox;
  map.fitBounds(
    [
      [west, south],
      [east, north],
    ],
    { padding: 48, maxZoom: 12, duration: 700 },
  );
}

function escapeHTML(value) {
  return String(value).replace(
    /[&<>"']/g,
    (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char],
  );
}

function propertiesTable(properties) {
  const entries = Object.entries(properties).filter(([, value]) => value !== null && value !== '');
  if (entries.length === 0) return '<p>No attributes.</p>';
  const rows = entries
    .map(([key, value]) => `<tr><th>${escapeHTML(key)}</th><td>${escapeHTML(value)}</td></tr>`)
    .join('');
  return `<table>${rows}</table>`;
}

function attachPopup(map, renderId, layer) {
  map.on('click', renderId, (event) => {
    const feature = event.features?.[0];
    if (!feature) return;

    let properties = {};
    try {
      properties = JSON.parse(feature.properties.props ?? '{}');
    } catch {
      properties = feature.properties ?? {};
    }

    new maplibregl.Popup({ maxWidth: '320px' })
      .setLngLat(event.lngLat)
      .setHTML(`<h3>${escapeHTML(layer.title)}</h3>${propertiesTable(properties)}`)
      .addTo(map);
  });

  map.on('mouseenter', renderId, () => {
    map.getCanvas().style.cursor = 'pointer';
  });
  map.on('mouseleave', renderId, () => {
    map.getCanvas().style.cursor = '';
  });
}
