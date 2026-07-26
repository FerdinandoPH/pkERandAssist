/* Lienzo unico del asistente.
 *
 * El mundo entero mide unos 25000 x 13000 px, asi que no puede ser una sola
 * imagen: cada mapa es un PNG independiente que se dibuja en su posicion, se
 * carga solo si entra en pantalla y usa el mipmap adecuado al zoom.
 */

const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d', { alpha: false });
const tooltip = document.getElementById('tooltip');

const COLORS = {
  background: '#0e1014',
  fogFill: '#171b22',
  fogStroke: '#232a35',
  sectionStroke: '#222834',
  sectionLabel: '#6b7688',
  visitedOutline: '#2f3a49',
  warpUnknown: '#6d7a8c',
  warpKnown: '#4ad6a0',
  link: 'rgba(88, 166, 255, .55)',
  linkBoth: 'rgba(74, 214, 160, .65)',
  player: '#ffd447',
  selection: '#e8b84b',
};

// A partir de que zoom se dibuja cada cosa.
const SHOW_WARPS_AT = 0.30;
const SHOW_MAP_LABELS_AT = 0.55;
const PANEL_WIDTH = 280;  // debe coincidir con #panel en app.css

const world = { width: 0, height: 0, tile: 16, maps: {}, sections: [] };
const state = { visited: new Set(), links: [], specials: [] };
const player = { map: null, x: 0, y: 0, seen: 0 };

const camera = { x: 0, y: 0, scale: 0.2 };
const options = { reveal: false, links: true, follow: true };
// Puertas de las que ya sabemos a donde llevan, como "MAP_ID:indice".
let knownLinks = new Set();
let selected = null;
let hovered = null;
let needsDraw = true;

/* ---------- imagenes ---------- */

const images = new Map();

function imageFor(layout, scale) {
  // Mipmaps: a poco zoom no tiene sentido descargar el PNG nativo.
  const suffix = scale >= 0.5 ? '' : scale >= 0.15 ? '.4' : '.16';
  const src = `/assets/${layout}${suffix}.png`;
  let entry = images.get(src);
  if (entry === undefined) {
    const image = new Image();
    entry = { image, ready: false };
    images.set(src, entry);
    image.onload = () => { entry.ready = true; needsDraw = true; };
    image.onerror = () => { entry.failed = true; };
    image.src = src;
  }
  return entry.ready ? entry.image : null;
}

/* ---------- camara ---------- */

function resize() {
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.floor(window.innerWidth * ratio);
  canvas.height = Math.floor(window.innerHeight * ratio);
  canvas.style.width = window.innerWidth + 'px';
  canvas.style.height = window.innerHeight + 'px';
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  needsDraw = true;
}

function viewport() {
  return {
    x: camera.x,
    y: camera.y,
    w: window.innerWidth / camera.scale,
    h: window.innerHeight / camera.scale,
  };
}

function toScreen(x, y) {
  return [(x - camera.x) * camera.scale, (y - camera.y) * camera.scale];
}

function toWorld(sx, sy) {
  return [sx / camera.scale + camera.x, sy / camera.scale + camera.y];
}

function fitAll() {
  const margin = 40;
  const viewWidth = window.innerWidth - PANEL_WIDTH - margin;
  const viewHeight = window.innerHeight - margin;
  camera.scale = Math.max(
    Math.min(viewWidth / world.width, viewHeight / world.height),
    0.01,
  );
  // Centrar el mundo en el hueco que deja el panel.
  camera.x = world.width / 2 - viewWidth / 2 / camera.scale - margin / 2 / camera.scale;
  camera.y = world.height / 2 - window.innerHeight / 2 / camera.scale;
  needsDraw = true;
}

function centerOn(mapId, scale) {
  const entry = world.maps[mapId];
  if (!entry) return;
  if (scale) camera.scale = scale;
  camera.x = entry.x + entry.w / 2 - (window.innerWidth - PANEL_WIDTH) / 2 / camera.scale;
  camera.y = entry.y + entry.h / 2 - window.innerHeight / 2 / camera.scale;
  needsDraw = true;
}

/* ---------- dibujo ---------- */

function visibleMaps() {
  const view = viewport();
  const found = [];
  for (const [id, entry] of Object.entries(world.maps)) {
    if (entry.x > view.x + view.w || entry.x + entry.w < view.x) continue;
    if (entry.y > view.y + view.h || entry.y + entry.h < view.y) continue;
    found.push([id, entry]);
  }
  return found;
}

function draw() {
  needsDraw = false;
  ctx.fillStyle = COLORS.background;
  ctx.fillRect(0, 0, window.innerWidth, window.innerHeight);
  ctx.imageSmoothingEnabled = false;

  drawSections();

  const visible = visibleMaps();
  for (const [id, entry] of visible) drawMap(id, entry);
  if (options.links) drawLinks();
  if (camera.scale >= SHOW_WARPS_AT) for (const [id, entry] of visible) drawWarps(id, entry);
  drawPlayer();
  drawSelection();
}

function drawSections() {
  ctx.lineWidth = 1;
  ctx.strokeStyle = COLORS.sectionStroke;
  ctx.fillStyle = COLORS.sectionLabel;
  ctx.textBaseline = 'top';
  // Tamano fijo en pixeles de pantalla: si escalara con el zoom, a vista de
  // pajaro los 64 rotulos se pisarian unos a otros.
  ctx.font = '600 12px "Segoe UI", sans-serif';

  for (const section of world.sections) {
    const [sx, sy] = toScreen(section.x, section.y);
    const w = section.w * camera.scale;
    const h = section.h * camera.scale;
    if (sx > window.innerWidth || sx + w < 0 || sy > window.innerHeight || sy + h < 0) continue;
    ctx.strokeRect(sx, sy, w, h);
    // El rotulo va dentro de la banda que el empaquetado le reserva arriba;
    // sacarlo fuera lo haria pisar la seccion de encima.
    if (w > 60 && ctx.measureText(section.label).width < w - 4) {
      ctx.fillText(section.label, sx + 3, sy + 2);
    }
  }
}

function drawMap(id, entry) {
  const [sx, sy] = toScreen(entry.x, entry.y);
  const w = entry.w * camera.scale;
  const h = entry.h * camera.scale;
  const known = options.reveal || state.visited.has(id);

  if (known) {
    const image = imageFor(entry.layout, camera.scale);
    if (image) {
      ctx.drawImage(image, sx, sy, w, h);
    } else {
      ctx.fillStyle = COLORS.fogFill;
      ctx.fillRect(sx, sy, w, h);
    }
    if (camera.scale > 0.2) {
      ctx.strokeStyle = COLORS.visitedOutline;
      ctx.lineWidth = 1;
      ctx.strokeRect(sx + .5, sy + .5, w - 1, h - 1);
    }
  } else {
    // Niebla: se ve la silueta y el nombre, pero no el contenido.
    ctx.fillStyle = COLORS.fogFill;
    ctx.fillRect(sx, sy, w, h);
    ctx.strokeStyle = COLORS.fogStroke;
    ctx.lineWidth = 1;
    ctx.strokeRect(sx + .5, sy + .5, w - 1, h - 1);
  }

  if (camera.scale >= SHOW_MAP_LABELS_AT && (known || camera.scale > 1)) {
    ctx.fillStyle = known ? 'rgba(230,238,248,.85)' : COLORS.sectionLabel;
    ctx.font = '500 11px "Segoe UI", sans-serif';
    ctx.textBaseline = 'top';
    ctx.fillText(entry.name, sx + 4, sy + 3);
  }
}

function warpPoint(mapId, warpIndex) {
  const entry = world.maps[mapId];
  if (!entry) return null;
  const warp = entry.warps[warpIndex];
  if (!warp) return null;
  return [entry.x + warp.x, entry.y + warp.y];
}

function drawWarps(id, entry) {
  const radius = Math.max(2.5, Math.min(7, 4 * camera.scale));
  for (let index = 0; index < entry.warps.length; index++) {
    const known = knownLinks.has(`${id}:${index}`);
    if (!options.reveal && !state.visited.has(id)) continue;
    const [wx, wy] = warpPoint(id, index);
    const [sx, sy] = toScreen(wx, wy);
    ctx.beginPath();
    ctx.arc(sx, sy, radius, 0, Math.PI * 2);
    ctx.fillStyle = known ? COLORS.warpKnown : COLORS.warpUnknown;
    ctx.globalAlpha = known ? 0.95 : 0.5;
    ctx.fill();
    ctx.globalAlpha = 1;
  }
}

function drawLinks() {
  ctx.lineWidth = Math.max(1, 1.6 * Math.min(camera.scale, 1.5));
  for (const link of state.links) {
    const from = warpPoint(link.from_map, link.from_warp);
    const to = warpPoint(link.to_map, link.to_warp);
    if (!from || !to) continue;
    const [x0, y0] = toScreen(from[0], from[1]);
    const [x1, y1] = toScreen(to[0], to[1]);
    // Descartar lo que queda claramente fuera de pantalla.
    if (Math.max(x0, x1) < 0 || Math.min(x0, x1) > window.innerWidth) continue;
    if (Math.max(y0, y1) < 0 || Math.min(y0, y1) > window.innerHeight) continue;

    // Curva suave: separa visualmente los tramos que se cruzan.
    const midX = (x0 + x1) / 2;
    const midY = (y0 + y1) / 2;
    const dx = x1 - x0, dy = y1 - y0;
    const distance = Math.hypot(dx, dy);
    const bulge = Math.min(distance * 0.18, 120);
    const cx = midX - (dy / (distance || 1)) * bulge;
    const cy = midY + (dx / (distance || 1)) * bulge;

    ctx.strokeStyle = link.return_seen ? COLORS.linkBoth : COLORS.link;
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.quadraticCurveTo(cx, cy, x1, y1);
    ctx.stroke();
  }
}

function drawPlayer() {
  if (!player.map) return;
  const entry = world.maps[player.map];
  if (!entry) return;
  const [sx, sy] = toScreen(
    entry.x + player.x * world.tile + world.tile / 2,
    entry.y + player.y * world.tile + world.tile / 2,
  );
  const pulse = 1 + 0.25 * Math.sin(Date.now() / 300);
  ctx.beginPath();
  ctx.arc(sx, sy, Math.max(4, 6 * camera.scale) * pulse, 0, Math.PI * 2);
  ctx.fillStyle = COLORS.player;
  ctx.fill();
  ctx.strokeStyle = '#1a1400';
  ctx.lineWidth = 1.5;
  ctx.stroke();
  needsDraw = true;  // la pulsacion necesita repintado continuo
}

function drawSelection() {
  const target = selected && world.maps[selected];
  if (!target) return;
  const [sx, sy] = toScreen(target.x, target.y);
  ctx.strokeStyle = COLORS.selection;
  ctx.lineWidth = 2;
  ctx.strokeRect(sx - 1, sy - 1, target.w * camera.scale + 2, target.h * camera.scale + 2);
}

/* ---------- interaccion ---------- */

let dragging = false;
let dragMoved = false;
let lastPointer = { x: 0, y: 0 };

canvas.addEventListener('pointerdown', (event) => {
  dragging = true;
  dragMoved = false;
  lastPointer = { x: event.clientX, y: event.clientY };
  canvas.classList.add('dragging');
  canvas.setPointerCapture(event.pointerId);
});

canvas.addEventListener('pointermove', (event) => {
  if (dragging) {
    const dx = event.clientX - lastPointer.x;
    const dy = event.clientY - lastPointer.y;
    if (Math.abs(dx) + Math.abs(dy) > 2) dragMoved = true;
    camera.x -= dx / camera.scale;
    camera.y -= dy / camera.scale;
    lastPointer = { x: event.clientX, y: event.clientY };
    options.follow = false;
    document.getElementById('opt-follow').checked = false;
    needsDraw = true;
    return;
  }
  updateHover(event.clientX, event.clientY);
});

canvas.addEventListener('pointerup', (event) => {
  dragging = false;
  canvas.classList.remove('dragging');
  canvas.releasePointerCapture(event.pointerId);
  if (!dragMoved) {
    const found = mapAt(event.clientX, event.clientY);
    selected = found;
    showSelection(found);
    needsDraw = true;
  }
});

canvas.addEventListener('wheel', (event) => {
  event.preventDefault();
  const [wx, wy] = toWorld(event.clientX, event.clientY);
  const factor = Math.exp(-event.deltaY * 0.0015);
  camera.scale = Math.min(4, Math.max(0.02, camera.scale * factor));
  // Mantener bajo el cursor el mismo punto del mundo.
  camera.x = wx - event.clientX / camera.scale;
  camera.y = wy - event.clientY / camera.scale;
  needsDraw = true;
}, { passive: false });

function mapAt(screenX, screenY) {
  const [wx, wy] = toWorld(screenX, screenY);
  for (const [id, entry] of Object.entries(world.maps)) {
    if (wx >= entry.x && wx <= entry.x + entry.w && wy >= entry.y && wy <= entry.y + entry.h) {
      return id;
    }
  }
  return null;
}

function updateHover(screenX, screenY) {
  const found = mapAt(screenX, screenY);
  if (found === hovered) return;
  hovered = found;
  if (!found) {
    tooltip.hidden = true;
    return;
  }
  const entry = world.maps[found];
  const known = options.reveal || state.visited.has(found);
  tooltip.textContent = known ? entry.name : '???';
  tooltip.style.left = (screenX + 14) + 'px';
  tooltip.style.top = (screenY + 14) + 'px';
  tooltip.hidden = false;
}

/* ---------- panel ---------- */

function showSelection(mapId) {
  const box = document.getElementById('selection');
  if (!mapId) { box.hidden = true; return; }
  const entry = world.maps[mapId];
  const known = options.reveal || state.visited.has(mapId);
  box.hidden = false;
  document.getElementById('sel-name').textContent = known ? entry.name : '???';
  document.getElementById('sel-zone').textContent = known ? entry.zone : 'sin explorar';

  const list = document.getElementById('sel-warps');
  list.innerHTML = '';
  entry.warps.forEach((_, index) => {
    const link = state.links.find(l => l.from_map === mapId && l.from_warp === index);
    const item = document.createElement('li');
    const idx = document.createElement('span');
    idx.className = 'idx';
    idx.textContent = index;
    const dest = document.createElement('span');
    if (link) {
      dest.className = 'dest' + (link.return_seen ? ' both' : '');
      const target = world.maps[link.to_map];
      dest.textContent = target ? target.name : link.to_map;
    } else {
      dest.className = 'unknown';
      dest.textContent = 'sin probar';
    }
    item.append(idx, dest);
    list.append(item);
  });
}

function refreshStats() {
  knownLinks = new Set(state.links.map(l => `${l.from_map}:${l.from_warp}`));
  const zones = new Set();
  for (const id of state.visited) {
    const entry = world.maps[id];
    if (entry && entry.kind === 'outdoor') zones.add(entry.zone);
  }
  document.getElementById('stat-zones').textContent = zones.size;
  document.getElementById('stat-maps').textContent = state.visited.size;
  document.getElementById('stat-doors').textContent = state.links.length;
  document.getElementById('stat-both').textContent =
    state.links.filter(l => l.return_seen).length;
  needsDraw = true;
}

function applyState(snapshot) {
  state.visited = new Set(snapshot.visited);
  state.links = snapshot.links;
  state.specials = snapshot.specials;
  refreshStats();
  if (selected) showSelection(selected);
  refreshPending();
}

// Se recalcula en el servidor, asi que se agrupan las peticiones seguidas.
let pendingTimer = null;

function refreshPending() {
  clearTimeout(pendingTimer);
  pendingTimer = setTimeout(async () => {
    const data = await (await fetch('/api/pending')).json();
    document.getElementById('pending-count').textContent = data.total;
    const list = document.getElementById('pending-list');
    list.innerHTML = '';
    for (const zone of data.zones) {
      const header = document.createElement('li');
      header.className = 'zone';
      header.textContent = zone.zone;
      list.append(header);
      for (const entry of zone.maps) {
        const item = document.createElement('li');
        item.className = 'entry';
        item.textContent = entry.name + ' ';
        const count = document.createElement('span');
        count.className = 'count';
        count.textContent = `(${entry.warps.length})`;
        item.append(count);
        // Click: llevar la camara a ese mapa para ver que puertas faltan.
        item.addEventListener('click', () => {
          options.follow = false;
          document.getElementById('opt-follow').checked = false;
          selected = entry.map;
          showSelection(entry.map);
          centerOn(entry.map, Math.max(camera.scale, 1));
        });
        list.append(item);
      }
    }
  }, 250);
}

function setPlayer(update) {
  player.map = update.map;
  player.x = update.x;
  player.y = update.y;
  player.seen = Date.now();
  const entry = world.maps[update.map];
  document.getElementById('current-map').textContent =
    entry ? entry.name : (update.map || '-');
  document.getElementById('current-pos').textContent =
    entry ? `${entry.zone} - (${update.x}, ${update.y})` : '';
  if (options.follow && entry) centerOn(update.map, Math.max(camera.scale, 0.8));
  needsDraw = true;
}

/* ---------- conexion ---------- */

function connect() {
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${protocol}://${location.host}/ws`);
  const status = document.getElementById('link-status');

  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === 'state') applyState(message.state);
    else if (message.type === 'visit') {
      state.visited.add(message.map);
      refreshStats();
      refreshPending();
    }
    else if (message.type === 'player') {
      setPlayer(message);
      status.textContent = 'emulador conectado';
      status.className = 'status online';
    } else if (message.type === 'link') {
      // El mismo par puede reenviarse al confirmarse en sentido contrario.
      const existing = state.links.find(
        l => l.from_map === message.link.from_map && l.from_warp === message.link.from_warp);
      if (existing) Object.assign(existing, message.link);
      else state.links.push(message.link);
      refreshStats();
      refreshPending();
      if (selected) showSelection(selected);
    } else if (message.type === 'bridge') {
      status.textContent = message.connected ? 'emulador conectado' : 'emulador sin conectar';
      status.className = 'status ' + (message.connected ? 'online' : 'offline');
    }
  };
  socket.onclose = () => {
    status.textContent = 'servidor desconectado';
    status.className = 'status offline';
    setTimeout(connect, 2000);
  };
  // Latido: mantiene viva la conexion a traves de proxies.
  setInterval(() => {
    if (socket.readyState === WebSocket.OPEN) socket.send('ping');
  }, 20000);
}

/* ---------- arranque ---------- */

document.getElementById('opt-reveal').addEventListener('change', (event) => {
  options.reveal = event.target.checked;
  if (selected) showSelection(selected);
  needsDraw = true;
});
document.getElementById('opt-links').addEventListener('change', (event) => {
  options.links = event.target.checked;
  needsDraw = true;
});
document.getElementById('opt-follow').addEventListener('change', (event) => {
  options.follow = event.target.checked;
});
document.getElementById('btn-fit').addEventListener('click', fitAll);
document.getElementById('btn-export').addEventListener('click', async () => {
  const data = await (await fetch('/api/export')).json();
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `puertas-${data.partida}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
});

window.addEventListener('resize', resize);

function loop() {
  if (needsDraw) draw();
  requestAnimationFrame(loop);
}

// Si algo revienta, mas vale decirlo que dejar el lienzo en negro.
function showError(what) {
  const box = document.getElementById('error');
  box.textContent = String(what && what.stack ? what.stack : what);
  box.hidden = false;
}

window.addEventListener('error', (event) => showError(event.error || event.message));
window.addEventListener('unhandledrejection', (event) => showError(event.reason));

async function start() {
  const data = await (await fetch('/api/world')).json();
  Object.assign(world, data);
  const snapshot = await (await fetch('/api/state')).json();
  applyState(snapshot);

  // ?reveal=1 abre el lienzo con todo destapado, para inspeccionarlo.
  if (new URLSearchParams(location.search).has('reveal')) {
    options.reveal = true;
    document.getElementById('opt-reveal').checked = true;
  }

  resize();
  fitAll();
  connect();
  loop();
}

start().catch(showError);
