"""Reproduce una traza del emulador y cuenta que decide el tracker.

    python tools/replay.py runs/trazas/traza-20260727-101500.jsonl

Las trazas las graba el asistente cuando se arranca con la traza activada
(`python launcher.py --trace`, o la variable PKER_TRACE). Sirven para
averiguar por que una puerta concreta no se registro: aqui se ve muestra a
muestra que transiciones salen y cuales se descartan, sin emulador y sin tocar
la partida.

Con --sospechosas solo se listan los cambios de mapa que NO acabaron en
puerta, que es lo que se suele estar buscando.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.state import Run  # noqa: E402
from app.tracker import Sample, Tracker  # noqa: E402
from common import DATA_DIR, load_json  # noqa: E402


def read_trace(path: Path) -> list[Sample]:
    """Las muestras de la traza, saltando los renglones ilegibles."""
    samples = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                samples.append(Sample(
                    map_group=data["map_group"], map_num=data["map_num"],
                    warp_id=data["warp_id"], x=data["x"], y=data["y"],
                    frame=data.get("frame", 0),
                ))
            except (ValueError, KeyError, TypeError):
                continue
    return samples


def build_tracker() -> Tracker:
    """Un tracker con los datos reales y una partida en memoria.

    La partida no se guarda: reproducir una traza no debe tocar runs/.
    """
    run = Run(name="replay")
    run.save = lambda: None  # type: ignore[method-assign]
    return Tracker(
        maps=load_json(DATA_DIR / "maps.json")["maps"],
        warps=load_json(DATA_DIR / "warps.json"),
        warp_tiles=load_json(DATA_DIR / "warp_tiles.json")
        if (DATA_DIR / "warp_tiles.json").is_file() else {},
        run=run,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traza", type=Path, help="fichero .jsonl grabado")
    parser.add_argument("--sospechosas", action="store_true",
                        help="solo los cambios de mapa que no dieron puerta")
    args = parser.parse_args(argv)

    if not args.traza.is_file():
        print(f"No encuentro {args.traza}", file=sys.stderr)
        return 1

    tracker = build_tracker()
    samples = read_trace(args.traza)
    if not samples:
        print("La traza no tiene ninguna muestra utilizable.", file=sys.stderr)
        return 1

    previous_map: str | None = None
    suspicious = 0
    for sample in samples:
        events = tracker.feed(sample)
        map_id = tracker.map_id_for(sample)
        moved = map_id is not None and previous_map is not None and map_id != previous_map

        for event in events:
            if event["type"] in ("link", "special") and not args.sospechosas:
                print(f"  [{sample.frame}] {tracker.describe(event)}")

        # Un cambio de mapa que no produce ni puerta ni transicion especial es
        # justo el sintoma de "no se ha registrado el enlace".
        if moved and not any(e["type"] in ("link", "special") for e in events):
            suspicious += 1
            name = tracker.maps.get(map_id, {}).get("name", map_id)
            print(f"  [{sample.frame}] SIN REGISTRAR: {previous_map} -> {name} "
                  f"en ({sample.x},{sample.y}) warp_id={sample.warp_id}")
        if map_id is not None:
            previous_map = map_id

    run = tracker.run
    print(f"\nmuestras: {len(samples)}   mapas: {len(run.visited)}   "
          f"puertas: {len(run.links)}   especiales: {len(run.specials)}   "
          f"cambios sin registrar: {suspicious}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
