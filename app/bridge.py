"""Recibe las lecturas que manda el script Lua de mGBA.

Escucha en 127.0.0.1:8765 y va pasando cada linea al Tracker. Corre en su
propio hilo para no depender del bucle de asyncio del servidor web, de modo
que tambien funciona en modo consola (`python -m app.bridge`).
"""

from __future__ import annotations

import json
import socket
import threading
from typing import Callable

from app.tracker import Sample, Tracker

HOST = "127.0.0.1"
PORT = 8765


class BridgeServer:
    def __init__(
        self,
        tracker: Tracker,
        host: str = HOST,
        port: int = PORT,
        on_connection: Callable[[bool], None] | None = None,
    ) -> None:
        self.tracker = tracker
        self.host = host
        self.port = port
        self.on_connection = on_connection
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.connected = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass

    # ---- interno ------------------------------------------------------

    def _serve(self) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self.host, self.port))
        self._server.listen(1)
        self._server.settimeout(1.0)

        while not self._stop.is_set():
            try:
                client, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._set_connected(True)
            try:
                self._read_client(client)
            finally:
                client.close()
                self._set_connected(False)

    def _set_connected(self, value: bool) -> None:
        if value == self.connected:
            return
        self.connected = value
        if self.on_connection is not None:
            self.on_connection(value)

    def _read_client(self, client: socket.socket) -> None:
        client.settimeout(1.0)
        buffer = b""
        while not self._stop.is_set():
            try:
                chunk = client.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return  # mGBA ha cerrado
            buffer += chunk
            # El Lua manda una linea JSON por lectura; pueden llegar juntas.
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                self._handle_line(line)

    def _handle_line(self, line: bytes) -> None:
        text = line.strip()
        if not text:
            return
        try:
            data = json.loads(text)
            sample = Sample(
                map_group=data["map_group"],
                map_num=data["map_num"],
                warp_id=data["warp_id"],
                x=data["x"],
                y=data["y"],
                frame=data.get("frame", 0),
            )
        except (ValueError, KeyError, TypeError):
            return  # linea corrupta: mejor perderla que caerse
        self.tracker.feed(sample)


def build_tracker(run, on_event=None) -> Tracker:
    """Monta un Tracker con los datos estaticos ya generados.

    Lanza DataMissing si faltan: antes reventaba con un FileNotFoundError
    crudo al importar app.server, y el aviso amable no llegaba a verse.
    """
    from app.datafiles import DATA_DIR, load_json

    warp_tiles_path = DATA_DIR / "warp_tiles.json"
    return Tracker(
        maps=load_json("maps.json")["maps"],
        warps=load_json("warps.json"),
        warp_tiles=load_json("warp_tiles.json") if warp_tiles_path.is_file() else {},
        on_event=on_event,
        run=run,
    )


def main() -> int:
    """Modo consola: imprime cada puerta que se descubre."""
    import sys
    from app.state import Run

    run = Run.load()
    tracker: Tracker | None = None

    def report(event: dict) -> None:
        if event["type"] == "player":
            return
        text = tracker.describe(event)
        if text:
            print(text, flush=True)

    tracker = build_tracker(run, on_event=report)
    server = BridgeServer(
        tracker,
        on_connection=lambda ok: print(
            "mGBA conectado" if ok else "mGBA desconectado", flush=True),
    )
    server.start()
    print(f"esperando a mGBA en {HOST}:{PORT} (Ctrl+C para salir)", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
