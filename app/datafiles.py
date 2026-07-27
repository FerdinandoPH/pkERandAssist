"""Acceso a los datos generados en data/static/.

Existe para que faltar los datos sea una situacion *contada*, no un
FileNotFoundError crudo: es lo primero que le pasa a quien clona el proyecto y
lanza el servidor sin generar nada.
"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "static"
ASSETS_DIR = PROJECT_ROOT / "assets" / "layouts"

# Sin estos tres no hay nada que dibujar. warp_tiles.json es opcional: el
# tracker funciona sin el, solo pierde el plan B de identificar la puerta por
# el behavior del metatile.
REQUIRED = ("maps.json", "warps.json", "world_layout.json")


class DataMissing(RuntimeError):
    """Faltan los datos generados. El mensaje explica como generarlos."""


def missing_files() -> list[str]:
    """Cuales de los ficheros imprescindibles no estan."""
    return [name for name in REQUIRED if not (DATA_DIR / name).is_file()]


def data_ready() -> bool:
    return not missing_files()


def setup_hint() -> str:
    faltan = missing_files()
    detalle = ", ".join(faltan) if faltan else "los datos generados"
    return (
        f"Falta {detalle} en {DATA_DIR}.\n"
        "Preparalo con:\n"
        "  python tools/setup.py\n"
        "que te pedira la ruta al clon de pret/pokeemerald y hara el resto."
    )


def load_json(name: str):
    path = DATA_DIR / name
    if not path.is_file():
        raise DataMissing(setup_hint())
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
