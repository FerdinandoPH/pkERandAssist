"""Simula al emulador para probar el asistente sin tener mGBA delante.

Se conecta al puerto del puente y manda las mismas lineas que enviaria el
script Lua, recorriendo un guion de ejemplo: salir de casa por una puerta que
lleva a otra parte, volver a entrar, y cruzar a una ruta contigua.

    python tools/simulate.py            # guion de ejemplo
    python tools/simulate.py --walk 40  # ademas pasea al azar
"""

from __future__ import annotations

import argparse
import json
import random
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.common import DATA_DIR, load_json  # noqa: E402

HOST, PORT = "127.0.0.1", 8765

# Un recorrido corto pero representativo: puerta, vuelta por la misma puerta
# (para confirmarla en los dos sentidos) y salida a una ruta por conexion.
SCRIPT = [
    ("MAP_LITTLEROOT_TOWN_BRENDANS_HOUSE_1F", 9, 6, 2),
    ("MAP_LITTLEROOT_TOWN_BRENDANS_HOUSE_1F", 9, 7, 2),
    ("MAP_LITTLEROOT_TOWN_BRENDANS_HOUSE_1F", 9, 8, 2),
    ("MAP_MOSSDEEP_CITY_GYM", 7, 35, 1),
    ("MAP_MOSSDEEP_CITY_GYM", 7, 34, 1),
    ("MAP_MOSSDEEP_CITY_GYM", 7, 35, 1),
    ("MAP_LITTLEROOT_TOWN_BRENDANS_HOUSE_1F", 9, 8, 0),
    ("MAP_LITTLEROOT_TOWN_BRENDANS_HOUSE_1F", 8, 8, 0),
    ("MAP_LITTLEROOT_TOWN", 5, 9, 1),
    # El paseo va casilla a casilla, como en el juego: saltarse posiciones
    # seria una traza que el emulador nunca produce.
    ("MAP_LITTLEROOT_TOWN", 6, 9, 1),
    ("MAP_LITTLEROOT_TOWN", 7, 9, 1),
    ("MAP_LITTLEROOT_TOWN", 8, 8, 1),
    ("MAP_LITTLEROOT_TOWN", 9, 6, 1),
    ("MAP_LITTLEROOT_TOWN", 10, 4, 1),
    ("MAP_LITTLEROOT_TOWN", 10, 2, 1),
    ("MAP_LITTLEROOT_TOWN", 10, 1, 1),
    ("MAP_LITTLEROOT_TOWN", 10, 0, 1),
    ("MAP_ROUTE101", 10, 39, -1),
    ("MAP_ROUTE101", 10, 38, -1),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--delay", type=float, default=0.35, help="segundos entre pasos")
    parser.add_argument("--walk", type=int, default=0,
                        help="pasos adicionales de paseo aleatorio al final")
    args = parser.parse_args()

    maps = {m["id"]: m for m in load_json(DATA_DIR / "maps.json")["maps"]}

    try:
        connection = socket.create_connection((args.host, args.port), timeout=5)
    except OSError as error:
        raise SystemExit(
            f"No pude conectar a {args.host}:{args.port} ({error}).\n"
            "Arranca antes el servidor:  uvicorn app.server:app"
        )

    def send(map_id: str, x: int, y: int, warp: int, frame: int) -> None:
        entry = maps[map_id]
        payload = json.dumps({
            "map_group": entry["map_group"], "map_num": entry["map_num"],
            "warp_id": warp, "x": x, "y": y, "frame": frame,
        })
        connection.sendall((payload + "\n").encode())
        print(f"  {entry['name']}  ({x}, {y})  warp={warp}")

    print(f"conectado a {args.host}:{args.port}")
    frame = 0
    with connection:
        for map_id, x, y, warp in SCRIPT:
            frame += 4
            send(map_id, x, y, warp, frame)
            time.sleep(args.delay)

        map_id, x, y, warp = SCRIPT[-1]
        for _ in range(args.walk):
            frame += 4
            x = max(0, x + random.choice((-1, 0, 1)))
            y = max(0, y + random.choice((-1, 0, 1)))
            send(map_id, x, y, warp, frame)
            time.sleep(args.delay)

    print("fin del guion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
