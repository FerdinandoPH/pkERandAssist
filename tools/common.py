"""Rutas y utilidades compartidas por los scripts de tools/."""

from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "static"
ASSETS_DIR = PROJECT_ROOT / "assets" / "layouts"
RUNS_DIR = PROJECT_ROOT / "runs"

DEFAULT_POKEEMERALD = PROJECT_ROOT.parent / "pokeemerald"


def resolve_pokeemerald(arg: str | None) -> Path:
    """Devuelve la ruta al clon de pret/pokeemerald, validando que sirve."""
    path = Path(arg).resolve() if arg else Path(
        os.environ.get("POKEEMERALD", DEFAULT_POKEEMERALD)
    ).resolve()
    if not (path / "data" / "maps" / "map_groups.json").is_file():
        raise SystemExit(
            f"No encuentro pokeemerald en {path}.\n"
            "Clónalo con:  git clone --depth 1 https://github.com/pret/pokeemerald.git\n"
            "y pásalo con --pokeemerald <ruta> o la variable POKEEMERALD."
        )
    return path


def load_json(path: Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        if compact:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
