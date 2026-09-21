/** Application entrypoint: load the layer catalogue and wire up the sidebar. */
import './style.css';
import { getHealth, listLayers, getTileJSON } from './api.js';
import { addLayer, createMap, fitToLayer, renderLayerId, setLayerVisible } from './map.js';

const listEl = document.getElementById('layer-list');
const statusEl = document.getElementById('status-bar');

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle('error', isError);
}

function layerCard(map, layer, index, onToggle) {
  const card = document.createElement('div');
  card.className = 'layer';

  const header = document.createElement('div');
  header.className = 'layer-header';

  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.id = `toggle-${layer.name}`;
  // Show the first couple of layers so the map is never blank on load.
  checkbox.checked = index < 2;
  checkbox.addEventListener('change', () => onToggle(layer, checkbox.checked));

  const title = document.createElement('label');
  title.className = 'layer-title';
  title.htmlFor = checkbox.id;
  title.textContent = layer.title;

  const zoomButton = document.createElement('button');
  zoomButton.className = 'zoom-to';
  zoomButton.type = 'button';
  zoomButton.textContent = 'zoom';
  zoomButton.disabled = !layer.bbox;
  zoomButton.addEventListener('click', () => fitToLayer(map, layer));

  header.append(checkbox, title, zoomButton);

  const meta = document.createElement('div');
  meta.className = 'layer-meta';
  const count = layer.feature_count.toLocaleString();
  meta.textContent = `${layer.geometry_type ?? 'Geometry'} · ${count} features · z${layer.min_zoom}–${layer.max_zoom}`;

  card.append(header, meta);
  return { card, checkbox };
}

async function start() {
  const map = createMap('map');

  let layers = [];
  try {
    layers = await listLayers();
  } catch (error) {
    listEl.innerHTML = '';
    const message = document.createElement('p');
    message.className = 'status error';
    message.textContent = `Could not reach the API: ${error.message}`;
    listEl.append(message);
    setStatus('API unavailable', true);
    return;
  }

  if (layers.length === 0) {
    listEl.innerHTML =
      '<p class="status">No layers yet. Load some with <code>geoplatform-etl load ./data</code>.</p>';
    setStatus('0 layers');
    return;
  }

  await map.once('load');
  listEl.innerHTML = '';

  const pending = [];
  layers.forEach((layer, index) => {
    const { card, checkbox } = layerCard(map, layer, index, (target, visible) => {
      setLayerVisible(map, renderLayerId(target), visible);
    });
    listEl.append(card);

    pending.push(
      getTileJSON(layer.name)
        .then((tilejson) => {
          const renderId = addLayer(map, layer, tilejson, index);
          setLayerVisible(map, renderId, checkbox.checked);
        })
        .catch((error) => {
          checkbox.disabled = true;
          // eslint-disable-next-line no-console
          console.error(`Layer ${layer.name} failed to load`, error);
        }),
    );
  });

  await Promise.all(pending);

  const firstVisible = layers.find((layer) => layer.bbox);
  if (firstVisible) fitToLayer(map, firstVisible);

  try {
    const health = await getHealth();
    setStatus(`${layers.length} layers · PostGIS ${health.postgis ?? 'unknown'}`);
  } catch {
    setStatus(`${layers.length} layers`);
  }
}

start();
