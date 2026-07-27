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
  linkHover: 'rgba(255, 255, 255, .9)',
  player: '#ffd447',
  selection: '#e8b84b',
};

// A partir de que zoom se dibuja cada cosa.
const SHOW_WARPS_AT = 0.30;
const SHOW_MAP_LABELS_AT = 0.55;
const PANEL_WIDTH = 280;  // debe coincidir con #panel en app.css
// Cuanto se ve el terreno que aun no has pisado, en modo mundo.
const DIM_ALPHA = 0.32;
const MIN_PIXELS_FOR_IMAGE = 6;

const MIN_SCALE = 0.01;
const MAX_SCALE = 4;
// Seguimiento: constante de tiempo (90 % del recorrido en ~300 ms) y el
// margen en pixeles de mundo por debajo del cual no merece la pena moverse.
const CHASE_TAU = 0.13;
const CHASE_DEADZONE = 1.5;
const FOLLOW_SCALE = 1.0;

const world = { width: 0, height: 0, tile: 16, maps: {}, sections: [] };
const state = { visited: new Set(), links: [], specials: [] };
const player = { map: null, x: 0, y: 0, seen: 0 };

const camera = { x: 0, y: 0, scale: 0.2 };

/* Modos de mapa:
 *   explore  el terreno aparece segun lo pisas
 *   world    el mundo se ve entero desde el principio, atenuado hasta pisarlo
 * En los dos, las conexiones se descubren igual: el modo solo afecta al
 * terreno, nunca a las puertas ni a los enlaces.
 */
const PREFS_KEY = 'pkerand.prefs.v1';
const DEFAULTS = { mapMode: 'explore', links: true, follow: true };
const MAP_MODES = ['explore', 'world'];
const options = { ...DEFAULTS };
// ?reveal=1 destapa ademas los nombres: es para inspeccionar, no se guarda.
let revealAll = false;

// Puertas de las que ya sabemos a donde llevan, como "MAP_ID:indice".
let knownLinks = new Set();
// Extremos de enlace, para senalarlos y saltar de uno a otro.
let linkEndpoints = [];
let hoveredEndpoint = null;
let selected = null;
let hovered = null;
let needsDraw = true;

function loadOptions() {
  try {
    const stored = JSON.parse(localStorage.getItem(PREFS_KEY) || '{}');
    Object.assign(options, DEFAULTS, stored);
  } catch (error) {
    Object.assign(options, DEFAULTS);
  }
  // Un valor guardado por una version anterior no debe dejar el lienzo raro.
  if (!MAP_MODES.includes(options.mapMode)) options.mapMode = DEFAULTS.mapMode;
  options.links = !!options.links;
  options.follow = !!options.follow;
}

function saveOptions() {
  // En modo privado localStorage lanza; perder la preferencia no es grave.
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(options));
  } catch (error) { /* sin persistencia, pero la sesion sigue */ }
}

// El DOM se escribe SIEMPRE desde options, nunca al reves: si no, el estado
// que el navegador restaura al recargar contradice al de JS.
function syncControls() {
  document.getElementById('opt-mode').value = options.mapMode;
  document.getElementById('opt-links').checked = options.links;
  const follow = document.getElementById('btn-follow');
  follow.setAttribute('aria-pressed', String(options.follow));
}

/* Se ve el terreno? En modo mundo, todo. */
function terrainVisible(mapId) {
  return revealAll || options.mapMode === 'world' || state.visited.has(mapId);
}

/* Sabemos que sitio es? Esto no lo destapa el modo mundo: el nombre y las
 * puertas de un mapa donde no has estado si serian destripe. */
function identityKnown(mapId) {
  return revealAll || state.visited.has(mapId);
}

/* ---------- imagenes ---------- */

const images = new Map();

// En modo mundo entran en pantalla los 441 mapas a la vez. Pedirlos todos
// satura el pool de conexiones del navegador y retrasa justo lo que el
// usuario esta mirando, asi que se despachan por tandas.
const MAX_INFLIGHT = 8;
let inflight = 0;
const pendingImages = [];

function startImage(entry) {
  inflight++;
  const done = () => {
    inflight--;
    const next = pendingImages.shift();
    if (next) startImage(next);
  };
  entry.image.onload = () => { entry.ready = true; needsDraw = true; done(); };
  entry.image.onerror = () => { entry.failed = true; done(); };
  entry.image.src = entry.src;
}

function imageFor(layout, scale) {
  // Mipmaps: a poco zoom no tiene sentido descargar el PNG nativo.
  const suffix = scale >= 0.5 ? '' : scale >= 0.15 ? '.4' : '.16';
  const src = `/assets/${layout}${suffix}.png`;
  let entry = images.get(src);
  if (entry === undefined) {
    entry = { image: new Image(), src, ready: false, failed: false };
    images.set(src, entry);
    if (inflight < MAX_INFLIGHT) startImage(entry);
    else pendingImages.push(entry);
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

function clampScale(scale) {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
}

/* Coloca la camara mirando a (wx, wy).
 *
 * Es la unica funcion que escribe camera.x/y. Todo lo demas razona en
 * terminos de "que punto del mundo estoy mirando": interpolar la esquina
 * mientras cambia el zoom hace que el punto mirado se desplace solo.
 */
function centerAt(wx, wy, scale) {
  if (scale) camera.scale = clampScale(scale);
  camera.x = wx - (window.innerWidth - PANEL_WIDTH) / 2 / camera.scale;
  camera.y = wy - window.innerHeight / 2 / camera.scale;
  needsDraw = true;
}

function cameraCenter() {
  return [
    camera.x + (window.innerWidth - PANEL_WIDTH) / 2 / camera.scale,
    camera.y + window.innerHeight / 2 / camera.scale,
  ];
}

function fitAllTarget() {
  const margin = 40;
  const scale = clampScale(Math.min(
    (window.innerWidth - PANEL_WIDTH - margin) / world.width,
    (window.innerHeight - margin) / world.height,
  ));
  return [world.width / 2, world.height / 2, scale];
}

function fitAll(options0 = {}) {
  const [wx, wy, scale] = fitAllTarget();
  if (options0.animate) cameraTo(wx, wy, scale);
  else { stopCameraTween(); centerAt(wx, wy, scale); }
}

function centerOn(mapId, scale, options0 = {}) {
  const entry = world.maps[mapId];
  if (!entry) return;
  const wx = entry.x + entry.w / 2;
  const wy = entry.y + entry.h / 2;
  if (options0.animate) cameraTo(wx, wy, scale);
  else { stopCameraTween(); centerAt(wx, wy, scale); }
}

/* ---------- movimiento de camara ---------- */

/* Dos mecanismos distintos, y no es duplicacion:
 *
 * - tween: un viaje con principio y final (ir al otro extremo de una puerta,
 *   "Ver todo"). Tiene duracion y easing.
 * - chase: perseguir un objetivo que se mueve (el jugador). Llega una lectura
 *   cada 4 frames del emulador; un tween reiniciado 15 veces por segundo no
 *   termina nunca y se ve a tirones. El lerp exponencial no tiene principio y
 *   converge sobre un blanco movil.
 */
const camTween = { active: false, start: 0, duration: 0, from: null, to: null };
const chase = { active: false, x: 0, y: 0 };
let lastFrame = 0;

function easeInOutCubic(t) {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

function stopCameraTween() {
  camTween.active = false;
}

function stopChase() {
  chase.active = false;
}

function cameraTo(wx, wy, scale, { duration = null, instant = false } = {}) {
  const target = clampScale(scale || camera.scale);
  if (instant) {
    stopCameraTween();
    centerAt(wx, wy, target);
    return;
  }
  const [cx, cy] = cameraCenter();
  const screens = Math.hypot(wx - cx, wy - cy) * camera.scale / window.innerWidth;
  camTween.from = { x: cx, y: cy, scale: camera.scale };
  camTween.to = { x: wx, y: wy, scale: target };
  // Un salto de media pantalla y otro de 25000 px no pueden durar lo mismo:
  // con duracion fija, el largo es un borron que desorienta.
  camTween.duration = duration !== null
    ? duration
    : 280 + 420 * Math.min(1, screens / 3);
  // En saltos largos, alejarse a mitad de camino y volver a acercarse. Es lo
  // que deja ver por donde se pasa en vez de un barrido ciego.
  camTween.arc = screens > 2 ? Math.min(camTween.from.scale, camTween.to.scale) * 0.55 : 0;
  camTween.start = performance.now();
  camTween.active = true;
}

function setChaseTarget(wx, wy) {
  chase.x = wx;
  chase.y = wy;
  chase.active = true;
}

// Devuelve true si ha movido la camara.
function updateCamera(now) {
  const delta = lastFrame ? Math.min((now - lastFrame) / 1000, 0.1) : 0;
  lastFrame = now;

  if (camTween.active) {
    const t = Math.min(1, (now - camTween.start) / camTween.duration);
    const k = easeInOutCubic(t);
    const { from, to } = camTween;
    // El zoom se interpola en logaritmico: lineal entre 0.03 y 1 se pasa casi
    // todo el trayecto cerca del maximo y da sensacion de tiron.
    let scale = from.scale * Math.pow(to.scale / from.scale, k);
    if (camTween.arc) {
      const dip = Math.sin(Math.PI * t);  // 0 en los extremos, 1 a mitad
      scale = scale * Math.pow(camTween.arc / scale, dip * 0.6);
    }
    centerAt(from.x + (to.x - from.x) * k, from.y + (to.y - from.y) * k, scale);
    if (t >= 1) camTween.active = false;
    return true;
  }

  if (chase.active && delta > 0) {
    const [cx, cy] = cameraCenter();
    const dx = chase.x - cx;
    const dy = chase.y - cy;
    // Zona muerta: sin esto la camara tiembla con el personaje quieto.
    if (Math.hypot(dx, dy) < CHASE_DEADZONE) return false;
    const k = 1 - Math.exp(-delta / CHASE_TAU);
    centerAt(cx + dx * k, cy + dy * k);
    return true;
  }

  return false;
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
  const visible = terrainVisible(id);
  const known = identityKnown(id);

  if (visible) {
    // Lo que se ve por el modo mundo pero no se ha pisado, atenuado. El
    // lienzo es opaco y el fondo ya esta pintado, asi que el alpha mezcla
    // con el: oscurece y desatura de una sola pasada.
    const dim = !state.visited.has(id) && !revealAll;
    // Por debajo de unos pocos pixeles el PNG no aporta nada sobre un
    // rectangulo, y son 441 descargas que no hacen falta.
    const image = (w >= MIN_PIXELS_FOR_IMAGE && h >= MIN_PIXELS_FOR_IMAGE)
      ? imageFor(entry.layout, camera.scale) : null;
    if (image) {
      if (dim) ctx.globalAlpha = DIM_ALPHA;
      ctx.drawImage(image, sx, sy, w, h);
      ctx.globalAlpha = 1;
    } else {
      ctx.fillStyle = COLORS.fogFill;
      ctx.fillRect(sx, sy, w, h);
    }
    if (camera.scale > 0.2) {
      // El borde va sin atenuar: la silueta debe leerse igual.
      ctx.strokeStyle = dim ? COLORS.fogStroke : COLORS.visitedOutline;
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

function warpRadius() {
  return Math.max(2.5, Math.min(7, 4 * camera.scale));
}

function drawWarps(id, entry) {
  // Las puertas de un mapa donde no has estado no se dibujan ni en modo
  // mundo: dirian donde hay puertas antes de llegar.
  if (!identityKnown(id)) return;
  const radius = warpRadius();
  for (let index = 0; index < entry.warps.length; index++) {
    const known = knownLinks.has(`${id}:${index}`);
    const [wx, wy] = warpPoint(id, index);
    const [sx, sy] = toScreen(wx, wy);

    // El extremo senalado y el del otro lado del mismo enlace: asi se ve a
    // donde vas antes de pulsar.
    const isHovered = hoveredEndpoint
      && hoveredEndpoint.mapId === id && hoveredEndpoint.warpIndex === index;
    const isTarget = hoveredEndpoint
      && hoveredEndpoint.toMap === id && hoveredEndpoint.toWarp === index;

    ctx.beginPath();
    ctx.arc(sx, sy, isHovered ? radius * 1.7 : radius, 0, Math.PI * 2);
    ctx.fillStyle = known ? COLORS.warpKnown : COLORS.warpUnknown;
    ctx.globalAlpha = known ? 0.95 : 0.5;
    ctx.fill();
    ctx.globalAlpha = 1;

    if (isHovered || isTarget) {
      ctx.beginPath();
      ctx.arc(sx, sy, (isHovered ? radius * 1.7 : radius) + 2, 0, Math.PI * 2);
      ctx.strokeStyle = isHovered ? '#fff' : COLORS.linkHover;
      ctx.lineWidth = 2;
      ctx.stroke();
    }
  }
}

function strokeLinkCurve(from, to) {
  const [x0, y0] = toScreen(from[0], from[1]);
  const [x1, y1] = toScreen(to[0], to[1]);
  // Descartar lo que queda claramente fuera de pantalla.
  if (Math.max(x0, x1) < 0 || Math.min(x0, x1) > window.innerWidth) return;
  if (Math.max(y0, y1) < 0 || Math.min(y0, y1) > window.innerHeight) return;

  // Curva suave: separa visualmente los tramos que se cruzan.
  const midX = (x0 + x1) / 2;
  const midY = (y0 + y1) / 2;
  const dx = x1 - x0, dy = y1 - y0;
  const distance = Math.hypot(dx, dy);
  const bulge = Math.min(distance * 0.18, 120);
  const cx = midX - (dy / (distance || 1)) * bulge;
  const cy = midY + (dx / (distance || 1)) * bulge;

  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.quadraticCurveTo(cx, cy, x1, y1);
  ctx.stroke();
}

function drawLinks() {
  const width = Math.max(1, 1.6 * Math.min(camera.scale, 1.5));
  ctx.lineWidth = width;
  const highlighted = hoveredEndpoint && hoveredEndpoint.link;
  for (const link of state.links) {
    if (link === highlighted) continue;  // va al final, por encima del resto
    const from = warpPoint(link.from_map, link.from_warp);
    const to = warpPoint(link.to_map, link.to_warp);
    if (!from || !to) continue;
    ctx.strokeStyle = link.return_seen ? COLORS.linkBoth : COLORS.link;
    strokeLinkCurve(from, to);
  }

  if (highlighted) {
    ctx.lineWidth = width * 2.2;
    ctx.strokeStyle = COLORS.linkHover;
    strokeLinkCurve([hoveredEndpoint.wx, hoveredEndpoint.wy],
                    [hoveredEndpoint.tx, hoveredEndpoint.ty]);
    ctx.lineWidth = width;
  }
}

// Donde esta el personaje en coordenadas de mundo. Las lecturas del emulador
// vienen en casillas, no en pixeles.
function playerWorldPoint() {
  const entry = player.map && world.maps[player.map];
  if (!entry) return null;
  return [
    entry.x + player.x * world.tile + world.tile / 2,
    entry.y + player.y * world.tile + world.tile / 2,
  ];
}

function drawPlayer() {
  const point = playerWorldPoint();
  if (!point) return;
  const [sx, sy] = toScreen(point[0], point[1]);
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

/* ---------- seguir al jugador ---------- */

// Apagar el seguimiento cuando el usuario toma el control de la camara.
// Vive en una funcion porque hay cuatro sitios que lo hacen y antes estaba
// copiado en dos y olvidado en los otros.
function stopFollow() {
  if (!options.follow) return;
  options.follow = false;
  saveOptions();
  syncControls();
  stopChase();
  // La camara se queda donde este: recuperar la vista anterior de golpe
  // seria otro salto no pedido.
}

function startFollow() {
  options.follow = true;
  saveOptions();
  syncControls();
  const point = playerWorldPoint();
  if (!point) return;  // sin emulador, se activa y ya seguira cuando llegue
  // Un viaje con easing hasta el personaje y, al llegar, el seguimiento
  // continuo. Sin esto, activarlo desde la vista general daria un lerp
  // larguisimo.
  cameraTo(point[0], point[1], FOLLOW_SCALE);
  setChaseTarget(point[0], point[1]);
}

/* ---------- interaccion ---------- */

let dragging = false;
let dragMoved = false;
let lastPointer = { x: 0, y: 0 };

canvas.addEventListener('pointerdown', (event) => {
  // Si agarras el mapa, el viaje en curso se acaba aqui: pelear contra la
  // animacion es lo que hace que un lienzo parezca roto.
  stopCameraTween();
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
    stopFollow();
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
    // Pinchar un extremo de puerta lleva al otro lado. Tiene prioridad sobre
    // seleccionar el mapa: si has acertado un circulo de 11 px, lo querias.
    const endpoint = endpointAt(event.clientX, event.clientY);
    if (endpoint) {
      travelTo(endpoint);
      needsDraw = true;
      return;
    }
    const found = mapAt(event.clientX, event.clientY);
    selected = found;
    showSelection(found);
    needsDraw = true;
  }
});

canvas.addEventListener('wheel', (event) => {
  event.preventDefault();
  stopCameraTween();
  const [wx, wy] = toWorld(event.clientX, event.clientY);
  const factor = Math.exp(-event.deltaY * 0.0015);
  camera.scale = clampScale(camera.scale * factor);
  if (chase.active) {
    // Siguiendo al jugador, anclar al cursor pelearia con el recentrado:
    // aqui el zoom es sobre el personaje.
    centerAt(chase.x, chase.y);
  } else {
    // Mantener bajo el cursor el mismo punto del mundo.
    camera.x = wx - event.clientX / camera.scale;
    camera.y = wy - event.clientY / camera.scale;
  }
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
  // Un extremo de puerta manda sobre el mapa que hay debajo: es lo pequeno y
  // lo accionable.
  const endpoint = endpointAt(screenX, screenY);
  if (endpoint !== hoveredEndpoint) {
    hoveredEndpoint = endpoint;
    canvas.classList.toggle('pointing', !!endpoint);
    needsDraw = true;  // el resaltado si se dibuja, al contrario que hovered
    hovered = null;    // forzar que se reescriba el tooltip al salir
  }
  if (endpoint) {
    const target = world.maps[endpoint.toMap];
    tooltip.textContent = `Ir a ${target ? target.name : endpoint.toMap} #${endpoint.toWarp}`;
    tooltip.style.left = (screenX + 14) + 'px';
    tooltip.style.top = (screenY + 14) + 'px';
    tooltip.hidden = false;
    return;
  }

  const found = mapAt(screenX, screenY);
  if (found === hovered) return;
  hovered = found;
  if (!found) {
    tooltip.hidden = true;
    return;
  }
  const entry = world.maps[found];
  tooltip.textContent = identityKnown(found) ? entry.name : '???';
  tooltip.style.left = (screenX + 14) + 'px';
  tooltip.style.top = (screenY + 14) + 'px';
  tooltip.hidden = false;
}

/* ---------- panel ---------- */

function showSelection(mapId) {
  const box = document.getElementById('selection');
  if (!mapId) { box.hidden = true; return; }
  const entry = world.maps[mapId];
  const known = identityKnown(mapId);
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

/* Los dos extremos de cada enlace descubierto, para poder senalarlos con el
 * raton y saltar de uno a otro. Se reconstruye con las estadisticas porque
 * ambos dependen de lo mismo y ya se recorria state.links. */
function rebuildLinkIndex() {
  linkEndpoints = [];
  for (const link of state.links) {
    const from = warpPoint(link.from_map, link.from_warp);
    const to = warpPoint(link.to_map, link.to_warp);
    if (!from || !to) continue;  // ids de otra version de los datos
    linkEndpoints.push({
      link, mapId: link.from_map, warpIndex: link.from_warp,
      wx: from[0], wy: from[1], tx: to[0], ty: to[1],
      toMap: link.to_map, toWarp: link.to_warp,
    });
    linkEndpoints.push({
      link, mapId: link.to_map, warpIndex: link.to_warp,
      wx: to[0], wy: to[1], tx: from[0], ty: from[1],
      toMap: link.from_map, toWarp: link.from_warp,
    });
  }
}

/* Extremo bajo el cursor, o null.
 *
 * Busqueda lineal a proposito: 1313 puertas dan como mucho 2626 extremos, y
 * recorrerlos es despreciable al lado del drawImage de los mapas del mismo
 * fotograma. Una rejilla espacial seria complejidad sin ganancia medible.
 */
function endpointAt(screenX, screenY) {
  // Si el circulo no se dibuja, no se puede pinchar.
  if (camera.scale < SHOW_WARPS_AT) return null;
  const reach = warpRadius() + 5;
  let best = null;
  let bestDistance = reach;
  for (const endpoint of linkEndpoints) {
    if (!identityKnown(endpoint.mapId)) continue;
    const [sx, sy] = toScreen(endpoint.wx, endpoint.wy);
    const distance = Math.hypot(sx - screenX, sy - screenY);
    // Gana el mas cercano, no el primero: a poco zoom hay puertas a pocos
    // pixeles y elegir la primera del array pareceria aleatorio.
    if (distance < bestDistance) {
      bestDistance = distance;
      best = endpoint;
    }
  }
  return best;
}

function travelTo(endpoint) {
  stopFollow();
  selected = endpoint.toMap;
  showSelection(selected);
  // Se conserva el zoom, pero nunca por debajo del umbral de las puertas:
  // al llegar tienes que ver los circulos para encadenar otro salto.
  cameraTo(endpoint.tx, endpoint.ty, Math.max(camera.scale, SHOW_WARPS_AT));
}

function refreshStats() {
  knownLinks = new Set(state.links.map(l => `${l.from_map}:${l.from_warp}`));
  rebuildLinkIndex();
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
  // Recargar en mitad de la partida no debe borrar donde estabas.
  if (snapshot.player) setPlayer(snapshot.player);
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
          stopFollow();
          selected = entry.map;
          showSelection(entry.map);
          centerOn(entry.map, Math.max(camera.scale, 1), { animate: true });
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
  if (options.follow) {
    const point = playerWorldPoint();
    // Se sigue al personaje, no al centro del mapa: en una ruta larga la
    // camara se quedaba plantada mientras el jugador se iba de pantalla.
    if (point) {
      // Primera lectura (o justo tras recargar con la opcion ya puesta):
      // acercarse con un viaje, no de un salto.
      if (!chase.active) cameraTo(point[0], point[1], FOLLOW_SCALE);
      setChaseTarget(point[0], point[1]);
    }
  }
  needsDraw = true;
}

/* ---------- partidas ---------- */

let currentRun = null;

// Los dialogos son los del navegador a proposito: esto es una aplicacion
// local de un solo usuario, y un modal propio son cien lineas para lo mismo.
async function callRuns(url, options0 = {}) {
  const response = await fetch(url, options0);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    alert(data.error || `Error ${response.status}`);
    return null;
  }
  return data;
}

async function refreshRuns() {
  const data = await callRuns('/api/runs');
  if (!data) return;
  currentRun = data.current;
  const select = document.getElementById('run-select');
  select.innerHTML = '';
  for (const entry of data.runs) {
    const option = document.createElement('option');
    option.value = entry.name;
    option.textContent = entry.error ? `${entry.name} (fichero danado)` : entry.name;
    option.selected = entry.name === data.current;
    select.append(option);
  }
  const active = data.runs.find(r => r.name === data.current);
  const plural = (n, singular, many) => `${n} ${n === 1 ? singular : many}`;
  document.getElementById('run-progress').textContent = active
    ? [plural(active.maps, 'mapa', 'mapas'),
       plural(active.links, 'puerta', 'puertas'),
       plural(active.confirmed, 'confirmada', 'confirmadas')].join(', ')
    : 'partida nueva';
}

document.getElementById('run-select').addEventListener('change', async (event) => {
  const name = event.target.value;
  if (name === currentRun) return;
  if (await callRuns(`/api/runs/${encodeURIComponent(name)}/select`, { method: 'POST' })) {
    await refreshRuns();
  }
});

document.getElementById('btn-run-new').addEventListener('click', async () => {
  const name = prompt('Nombre de la partida nueva:', '');
  if (!name) return;
  if (await callRuns('/api/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })) await refreshRuns();
});

document.getElementById('btn-run-rename').addEventListener('click', async () => {
  const to = prompt('Nuevo nombre:', currentRun || '');
  if (!to || to === currentRun) return;
  if (await callRuns(`/api/runs/${encodeURIComponent(currentRun)}/rename`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ to }),
  })) await refreshRuns();
});

document.getElementById('btn-run-delete').addEventListener('click', async () => {
  // El progreso va en el texto: es lo que de verdad evita el borrado tonto.
  const detail = document.getElementById('run-progress').textContent;
  if (!confirm(`Borrar la partida "${currentRun}"?\n${detail}\n\nNo se puede deshacer.`)) return;
  if (await callRuns(`/api/runs/${encodeURIComponent(currentRun)}`, { method: 'DELETE' })) {
    await refreshRuns();
  }
});

document.getElementById('btn-run-save').addEventListener('click', async () => {
  // El volcado crudo, que es lo que admite la importacion. "Exportar" sigue
  // dando el informe legible, que pierde datos y no vale para volver.
  const data = await callRuns(`/api/runs/${encodeURIComponent(currentRun)}/raw`);
  if (!data) return;
  const blob = new Blob([JSON.stringify(data, null, 1)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `${currentRun}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
});

document.getElementById('btn-run-import').addEventListener('click', () => {
  document.getElementById('run-file').click();
});

document.getElementById('run-file').addEventListener('change', async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  event.target.value = '';  // permite reimportar el mismo fichero
  let parsed;
  try {
    parsed = JSON.parse(await file.text());
  } catch (error) {
    alert('Ese fichero no es JSON valido.');
    return;
  }
  const name = prompt('Nombre para la partida importada:',
                      file.name.replace(/\.json$/i, ''));
  if (!name) return;
  const result = await callRuns('/api/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, data: parsed }),
  });
  if (!result) return;
  await refreshRuns();
  if (result.avisos && result.avisos.length) {
    alert(`Importada como "${result.name}", con avisos:\n- ${result.avisos.join('\n- ')}`);
  }
});

/* ---------- conexion ---------- */

function connect() {
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${protocol}://${location.host}/ws`);
  const status = document.getElementById('link-status');

  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === 'state') {
      // Llega al cambiar de partida (quiza desde otra pestana): el selector
      // tiene que reflejarlo.
      applyState(message.state);
      refreshRuns();
    }
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
  // Latido: mantiene viva la conexion a traves de proxies.
  const heartbeat = setInterval(() => {
    if (socket.readyState === WebSocket.OPEN) socket.send('ping');
  }, 20000);

  socket.onclose = () => {
    // Sin esto cada reconexion dejaba un latido vivo sobre un socket muerto.
    clearInterval(heartbeat);
    status.textContent = 'servidor desconectado';
    status.className = 'status offline';
    setTimeout(connect, 2000);
  };
}

/* ---------- arranque ---------- */

document.getElementById('opt-mode').addEventListener('change', (event) => {
  options.mapMode = event.target.value;
  saveOptions();
  needsDraw = true;
});
document.getElementById('opt-links').addEventListener('change', (event) => {
  options.links = event.target.checked;
  saveOptions();
  needsDraw = true;
});
document.getElementById('btn-follow').addEventListener('click', () => {
  if (options.follow) stopFollow();
  else startFollow();
  needsDraw = true;
});
document.getElementById('btn-fit').addEventListener('click', () => {
  // Mirar el mundo entero es elegir otro sitio que mirar: apaga el seguimiento.
  stopFollow();
  fitAll();
});
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

function loop(now) {
  if (updateCamera(now || performance.now())) needsDraw = true;
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
  loadOptions();
  // Overrides por URL, para inspeccionar o para una captura sin tocar las
  // preferencias guardadas: ?reveal=1 destapa tambien los nombres, y
  // ?mode=world fuerza el modo de mapa solo en esta carga.
  const query = new URLSearchParams(location.search);
  revealAll = query.has('reveal');
  if (MAP_MODES.includes(query.get('mode'))) options.mapMode = query.get('mode');
  syncControls();

  const data = await (await fetch('/api/world')).json();
  Object.assign(world, data);
  const snapshot = await (await fetch('/api/state')).json();
  applyState(snapshot);
  await refreshRuns();

  resize();
  // Si ya venimos siguiendo al jugador, el encuadre lo manda el seguimiento;
  // un fitAll aqui lo pisaria justo despues de colocarse.
  if (!chase.active) fitAll();
  connect();
  loop();
}

start().catch(showError);
