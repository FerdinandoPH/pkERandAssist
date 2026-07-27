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

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bridge import BridgeServer, build_tracker, trace_path_from_env  # noqa: E402
from app.datafiles import (  # noqa: E402
    ASSETS_DIR, DataMissing, data_ready, load_json, setup_hint,
)
from app.state import (  # noqa: E402
    Run, list_runs, run_path, safe_run_name, validate_payload,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


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
# navegador segun ocurre. Sin los datos generados no se puede montar, pero el
# servidor debe arrancar igual para poder explicar que falta.
tracker = None
bridge = None
if data_ready():
    tracker = build_tracker(run, on_event=lambda event: hub.broadcast_soon(event))
    bridge = BridgeServer(
        tracker,
        on_connection=lambda ok: hub.broadcast_soon({"type": "bridge", "connected": ok}),
        trace=trace_path_from_env(),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    hub.loop = asyncio.get_running_loop()
    if bridge is not None:
        bridge.start()
    else:
        print(setup_hint(), flush=True)
    try:
        yield
    finally:
        if bridge is not None:
            bridge.stop()


app = FastAPI(title="pkERandAssist", lifespan=lifespan)

if ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(DataMissing)
async def data_missing_handler(request: Request, exc: DataMissing):
    return JSONResponse(status_code=503, content={"error": str(exc)})


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    # Nombres de partida imposibles y ficheros de importacion invalidos: es
    # culpa de lo que llega, no del servidor.
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/")
async def index():
    if not data_ready():
        # Sin datos el lienzo se quedaria en negro sin decir por que.
        return HTMLResponse(
            "<!doctype html><meta charset='utf-8'>"
            "<title>pkERandAssist - falta preparar los datos</title>"
            "<body style='font:16px system-ui;background:#0e1014;color:#e6eef8;"
            "padding:3rem;line-height:1.6'>"
            "<h1>Falta preparar los datos</h1><pre style='background:#171b22;"
            f"padding:1rem;border-radius:6px;white-space:pre-wrap'>{setup_hint()}</pre>"
            "<p>Cuando termine, reinicia el servidor y recarga esta pagina.</p>",
            status_code=503,
        )
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


def current_state() -> dict:
    """Progreso mas la ultima posicion conocida, si el emulador ya ha hablado."""
    snapshot = run.snapshot()
    snapshot["player"] = tracker.last_player() if tracker is not None else None
    return snapshot


@app.get("/api/state")
async def state():
    return JSONResponse(current_state())


@app.post("/api/reset")
async def reset():
    run.reset()
    await hub.broadcast({"type": "state", "state": current_state()})
    return JSONResponse(current_state())


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


async def switch_run(name: str) -> JSONResponse:
    """Cambia de partida y pone al dia a los navegadores conectados."""
    run.switch_to(name)
    if tracker is not None:
        tracker.forget_history()
    await hub.broadcast({"type": "state", "state": current_state()})
    return JSONResponse(current_state())


@app.get("/api/runs")
async def runs_list():
    return JSONResponse({"current": run.name, "runs": list_runs()})


@app.post("/api/runs")
async def runs_create(payload: dict):
    name = safe_run_name(payload.get("name", ""))
    if run_path(name).is_file():
        return JSONResponse(status_code=409,
                            content={"error": f"Ya existe una partida '{name}'."})
    Run(name=name).save()
    return await switch_run(name)


@app.post("/api/runs/{name}/select")
async def runs_select(name: str):
    return await switch_run(name)


@app.post("/api/runs/{name}/rename")
async def runs_rename(name: str, payload: dict):
    source = run_path(name)
    target = run_path(payload.get("to", ""))
    if not source.is_file():
        return JSONResponse(status_code=404,
                            content={"error": f"No existe la partida '{name}'."})
    if target != source and target.is_file():
        # Path.replace sobreescribe sin avisar en las dos plataformas, asi que
        # comprobarlo antes es lo unico que evita perder una partida.
        return JSONResponse(status_code=409,
                            content={"error": f"Ya existe '{target.stem}'."})
    source.replace(target)
    if run.name == source.stem:
        return await switch_run(target.stem)
    return JSONResponse({"current": run.name, "runs": list_runs()})


@app.delete("/api/runs/{name}")
async def runs_delete(name: str):
    path = run_path(name)
    if not path.is_file():
        return JSONResponse(status_code=404,
                            content={"error": f"No existe la partida '{name}'."})
    path.unlink()
    if run.name == path.stem:
        # Hay que quedarse en alguna: la mas reciente, o una nueva por defecto.
        remaining = list_runs()
        await switch_run(remaining[0]["name"] if remaining else "default")
    return JSONResponse({"current": run.name, "runs": list_runs()})


@app.get("/api/runs/{name}/raw")
async def runs_raw(name: str):
    """Volcado crudo, que es el formato que admite la importacion."""
    path = run_path(name)
    if not path.is_file():
        return JSONResponse(status_code=404,
                            content={"error": f"No existe la partida '{name}'."})
    with open(path, encoding="utf-8") as fh:
        return JSONResponse(json.load(fh))


@app.post("/api/import")
async def import_run(payload: dict):
    content, warnings = validate_payload(payload.get("data"))
    name = safe_run_name(payload.get("name") or "importada")
    if run_path(name).is_file():
        return JSONResponse(status_code=409,
                            content={"error": f"Ya existe una partida '{name}'."})
    Run(name=name).save()
    await switch_run(name)
    run.replace_with(content)
    await hub.broadcast({"type": "state", "state": current_state()})
    return JSONResponse({"name": name, "avisos": warnings})


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
        await websocket.send_json({"type": "state", "state": current_state()})
        await websocket.send_json(
            {"type": "bridge", "connected": bridge is not None and bridge.connected})
        while True:
            await websocket.receive_text()  # el cliente solo mantiene la conexion
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unregister(websocket)
