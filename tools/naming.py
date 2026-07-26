"""Nombres legibles a partir de los identificadores del decomp.

`LittlerootTown_BrendansHouse_1F` -> `Littleroot Town - Brendan's House 1F`

Los nombres en castellano se resuelven en `data/i18n/es_overrides.json`, que
tiene prioridad sobre lo que genera este modulo. La idea es no inventar
traducciones: lo que no este en el fichero de overrides se queda en ingles.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Siglas y sufijos que no deben partirse por CamelCase.
_ATOMS = [
    "SSTidal", "PokeCenter", "PokemonCenter", "PokemonLeague", "PokeMart",
    "B1F", "B2F", "B3F", "B4F", "1F", "2F", "3F", "4F", "5F", "6F", "7F", "8F", "9F",
    "1R", "2R", "3R", "1P", "2P", "3P", "NPC",
]

# Retoques sobre el texto ya separado.
_FIXUPS = [
    (r"\bSS Tidal\b", "S.S. Tidal"),
    (r"\bMt\b", "Mt."),
    (r"\bPokemon\b", "Pokemon"),
    (r"\b(Brendans|Mays|Rivals|Players|Captains|Stevens|Wallys|Lanettes|Birchs)\b",
     lambda m: m.group(1)[:-1] + "'s"),
    (r"\bRoute(\d+)\b", r"Route \1"),
    (r"\s+", " "),
]

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[a-zA-Z])(?=\d)")

# Segmentos que son un sufijo del anterior (planta, sala) y no una parte nueva
# del nombre: `..._Gym_1F` es "Gym 1F", no "Gym - 1F".
_SUFFIX = re.compile(r"^(B?\d+[FRP]|\d+)$")

# Palabras que van en minuscula cuando no encabezan el nombre.
_LOWER = {"Of", "The", "And", "In", "On"}


def _split_segment(segment: str) -> str:
    for atom in _ATOMS:
        if segment == atom:
            return atom
    return _CAMEL.sub(" ", segment)


def humanize(map_name: str) -> str:
    """Convierte `MossdeepCity_Gym` en `Mossdeep City - Gym`."""
    parts = [p for p in map_name.split("_") if p]
    chunks: list[str] = []
    for part in parts:
        text = _split_segment(part)
        if chunks and _SUFFIX.match(part):
            chunks[-1] += f" {text}"
        else:
            chunks.append(text)
    text = " - ".join(chunks)
    for pattern, repl in _FIXUPS:
        text = re.sub(pattern, repl, text)
    words = text.split(" ")
    text = " ".join(
        w.lower() if i and w in _LOWER else w for i, w in enumerate(words)
    )
    return text.strip()


def load_overrides(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def mapsec_label(mapsec: str) -> str:
    """`MAPSEC_LITTLEROOT_TOWN` -> `Littleroot Town`."""
    body = mapsec.removeprefix("MAPSEC_")
    text = " ".join(w.capitalize() for w in body.split("_"))
    for pattern, repl in _FIXUPS:
        text = re.sub(pattern, repl, text)
    return text
