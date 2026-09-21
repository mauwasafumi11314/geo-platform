/**
 * Thin wrapper around the GeoPlatform HTTP API.
 *
 * In development Vite proxies these paths to the FastAPI process, so the
 * browser stays on a single origin. Set VITE_API_BASE to point a production
 * build at an API on another host.
 */
const API_BASE = import.meta.env.VITE_API_BASE ?? '';

async function getJSON(path) {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`${path} responded ${response.status} ${response.statusText}`);
  }
  return response.json();
}

export function listLayers() {
  return getJSON('/api/layers').then((body) => body.layers);
}

export function getTileJSON(layerName) {
  return getJSON(`/api/layers/${encodeURIComponent(layerName)}/tilejson`);
}

export function getHealth() {
  return getJSON('/health');
}

export { API_BASE };
