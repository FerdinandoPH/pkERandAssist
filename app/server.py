"""Servidor del asistente: sirve el lienzo y publica el estado en vivo.

    uvicorn app.server:app --reload

Rutas:
    /                 el lienzo
    /api/world        geometria del mundo (mapas, warps, secciones)
    /api/state        progreso de la partida
    /ws               empuja los cambios al navegador segun ocurren
"""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bridge import BridgeServer, build_tracker  # noqa: E402
from app.state import Run  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "static"
ASSETS_DIR = PROJECT_ROOT / "assets" / "layouts"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def load_json(name: str):
    path = DATA_DIR / name
    if not path.is_file():
        raise SystemExit(
            f"Falta {path}.\n"
            "Genera los datos primero:\n"
            "  python tools/build_data.py --pokeemerald <ruta>\n"
            "  python tools/render_maps.py --pokeemerald <ruta>\n"
            "  python tools/build_layout.py"
        )
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class Hub:
    """Reparte los eventos del tracker a los navegadores conectados."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def register(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.add(websocket)

    async def unregister(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            clients = list(self._clients)
        for client in clients:
            try:
                await client.send_json(message)
            except Exception:
                await self.unregister(client)

    def broadcast_soon(self, message: dict) -> None:
        """Version para hilos ajenos al bucle de asyncio (el puente TCP)."""
        if self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(message), self.loop)


hub = Hub()
run = Run.load()

# El tracker recibe las lecturas del emulador y va empujando cada hallazgo al
# navegador segun ocurre.
tracker = build_tracker(run, on_event=lambda event: hub.broadcast_soon(event))
bridge = BridgeServer(
    tracker,
    on_connection=lambda ok: hub.broadcast_soon({"type": "bridge", "connected": ok}),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    hub.loop = asyncio.get_running_loop()
    bridge.start()
    try:
        yield
    finally:
        bridge.stop()


app = FastAPI(title="pkERandAssist", lifespan=lifespan)

if ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/world")
async def world():
    """Todo lo que el lienzo necesita para dibujar, en una sola carga."""
    layout = load_json("world_layout.json")
    maps = load_json("maps.json")["maps"]
    warps = load_json("warps.json")

    tile = layout["tile_size"]
    entries = {}
    for entry in maps:
        placement = layout["placements"].get(entry["id"])
        if placement is None:
            continue
        entries[entry["id"]] = {
            "name": entry["name"],
            "zone": entry["mapsec_name"],
            "kind": placement["kind"],
            "layout": placement["layout"],
            "x": placement["x"], "y": placement["y"],
            "w": placement["w"], "h": placement["h"],
            # Posicion de cada puerta en pixeles, centrada en su casilla.
            "warps": [
                {"x": w["x"] * tile + tile // 2, "y": w["y"] * tile + tile // 2}
                for w in warps.get(entry["id"], [])
            ],
        }

    return JSONResponse({
        "width": layout["width"],
        "height": layout["height"],
        "tile": tile,
        "sections": layout["sections"],
        "maps": entries,
    })


@app.get("/api/state")
async def state():
    return JSONResponse(run.snapshot())


@app.post("/api/reset")
async def reset():
    run.reset()
    await hub.broadcast({"type": "state", "state": run.snapshot()})
    return JSONResponse(run.snapshot())


@app.get("/api/pending")
async def pending():
    """Puertas ya vistas cuyo destino sigue sin probar, agrupadas por zona."""
    maps = {m["id"]: m for m in load_json("maps.json")["maps"]}
    warps = load_json("warps.json")
    snapshot = run.snapshot()
    known = {f"{link['from_map']}:{link['from_warp']}" for link in snapshot["links"]}

    zones: dict[str, list] = {}
    for map_id in snapshot["visited"]:
        entry = maps.get(map_id)
        if entry is None:
            continue
        missing = [
            index for index in range(len(warps.get(map_id) or []))
            if f"{map_id}:{index}" not in known
        ]
        if missing:
            zones.setdefault(entry["mapsec_name"], []).append({
                "map": map_id, "name": entry["name"], "warps": missing,
            })

    return JSONResponse({
        "zones": [
            {"zone": zone, "maps": sorted(entries, key=lambda e: e["name"])}
            for zone, entries in sorted(zones.items())
        ],
        "total": sum(len(e["warps"]) for entries in zones.values() for e in entries),
    })


@app.get("/api/export")
async def export():
    """Vuelca lo descubierto con nombres legibles, para guardarlo o compartirlo."""
    maps = {m["id"]: m for m in load_json("maps.json")["maps"]}
    snapshot = run.snapshot()

    def name_of(map_id: str) -> str:
        return maps.get(map_id, {}).get("name", map_id)

    return JSONResponse({
        "partida": snapshot["name"],
        "mapas_visitados": [
            {"id": map_id, "nombre": name_of(map_id)} for map_id in snapshot["visited"]
        ],
        "puertas": [
            {
                "desde": f"{name_of(link['from_map'])} #{link['from_warp']}",
                "hasta": f"{name_of(link['to_map'])} #{link['to_warp']}",
                "confirmada_ida_y_vuelta": link["return_seen"],
                "ids": [link["from_map"], link["from_warp"],
                        link["to_map"], link["to_warp"]],
            }
            for link in snapshot["links"]
        ],
        "otras_transiciones": [
            {
                "tipo": special["kind"],
                "desde": name_of(special["from_map"]),
                "hasta": name_of(special["to_map"]),
                "detalle": special["detail"],
            }
            for special in snapshot["specials"]
        ],
    })


@app.post("/api/visit/{map_id}")
async def visit(map_id: str):
    """Marca un mapa a mano. Util para probar el lienzo sin el emulador."""
    changed = run.visit(map_id)
    if changed:
        await hub.broadcast({"type": "visit", "map": map_id})
    return JSONResponse({"changed": changed})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await hub.register(websocket)
    try:
        await websocket.send_json({"type": "state", "state": run.snapshot()})
        await websocket.send_json({"type": "bridge", "connected": bridge.connected})
        while True:
            await websocket.receive_text()  # el cliente solo mantiene la conexion
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unregister(websocket)
