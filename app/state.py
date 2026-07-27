"""Estado de una partida: que has pisado y que puertas has confirmado.

Se guarda en runs/<nombre>.json despues de cada cambio, para que cerrar la
aplicacion (o el emulador) no pierda nada.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"

# Nombres que Windows no admite como fichero. Se vetan aunque se desarrolle en
# Linux: la aplicacion tiene que funcionar en las dos plataformas.
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}
MAX_NAME_LENGTH = 40


def safe_run_name(name: str) -> str:
    """Nombre de partida utilizable como fichero, en Windows y en Linux.

    Sin esto, Run(name="../../algo") escribia fuera del proyecto.
    """
    cleaned = re.sub(r"[^A-Za-z0-9 _.-]", "", str(name)).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    # Windows se come los puntos y espacios finales, asi que el fichero
    # acabaria llamandose distinto de lo que se pidio.
    cleaned = cleaned.rstrip(". ")
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("El nombre de la partida no puede quedar vacio.")
    if cleaned.upper() in RESERVED_NAMES:
        raise ValueError(f"'{cleaned}' es un nombre reservado en Windows.")
    return cleaned[:MAX_NAME_LENGTH].rstrip(". ")


def run_path(name: str) -> Path:
    """Ruta del fichero de una partida, comprobando que cae dentro de runs/."""
    path = RUNS_DIR / f"{safe_run_name(name)}.json"
    if path.resolve().parent != RUNS_DIR.resolve():
        raise ValueError("Nombre de partida no valido.")
    return path


def list_runs() -> list[dict]:
    """Las partidas guardadas con su progreso, de la mas reciente a la mas vieja."""
    if not RUNS_DIR.is_dir():
        return []
    entries = []
    for path in RUNS_DIR.glob("*.json"):
        entry = {"name": path.stem, "maps": 0, "links": 0, "confirmed": 0,
                 "updated": 0.0, "error": False}
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            links = list((data.get("links") or {}).values())
            entry.update(
                maps=len(data.get("visited") or {}),
                links=len(links),
                confirmed=sum(1 for link in links if link.get("return_seen")),
                updated=data.get("updated", 0.0),
            )
        except (OSError, ValueError, AttributeError):
            # Un fichero corrupto se lista marcado, no tumba el listado entero.
            entry["error"] = True
        entries.append(entry)
    return sorted(entries, key=lambda e: e["updated"], reverse=True)


def validate_payload(data: object) -> tuple[dict, list[str]]:
    """Normaliza una partida importada. Devuelve (contenido, avisos).

    Funcion pura, sin tocar disco, para poder probarla sola. Descarta las
    entradas mal formadas contando avisos en vez de rechazar el fichero
    entero: un volcado al que le falte un campo sigue siendo util.
    """
    if not isinstance(data, dict):
        raise ValueError("El fichero no contiene un objeto JSON.")
    if "visited" not in data and "links" not in data:
        raise ValueError("El fichero no parece una partida (sin 'visited' ni 'links').")

    warnings: list[str] = []

    visited: dict[str, float] = {}
    source = data.get("visited") or {}
    # snapshot() devuelve una lista y el fichero de disco un diccionario:
    # se aceptan los dos, porque el usuario puede pegar cualquiera.
    if isinstance(source, list):
        for map_id in source:
            if isinstance(map_id, str):
                visited[map_id] = 0.0
    elif isinstance(source, dict):
        for map_id, seen in source.items():
            visited[map_id] = seen if isinstance(seen, (int, float)) else 0.0
    else:
        warnings.append("'visited' ignorado: no es ni lista ni diccionario.")

    links: dict[str, dict] = {}
    raw_links = data.get("links") or {}
    candidates = raw_links.values() if isinstance(raw_links, dict) else raw_links
    discarded = 0
    if isinstance(candidates, (list, tuple)) or hasattr(candidates, "__iter__"):
        for link in candidates:
            if not isinstance(link, dict):
                discarded += 1
                continue
            try:
                source_map = str(link["from_map"])
                source_warp = int(link["from_warp"])
                entry = {
                    "from_map": source_map, "from_warp": source_warp,
                    "to_map": str(link["to_map"]), "to_warp": int(link["to_warp"]),
                    "return_seen": bool(link.get("return_seen", False)),
                    "first_seen": link.get("first_seen", 0.0),
                }
            except (KeyError, TypeError, ValueError):
                discarded += 1
                continue
            links[link_key(source_map, source_warp)] = entry
    if discarded:
        warnings.append(f"{discarded} puertas descartadas por estar mal formadas.")

    specials = [s for s in (data.get("specials") or []) if isinstance(s, dict)]

    return {
        "visited": visited, "links": links, "specials": specials,
        "updated": data.get("updated", 0.0) or time.time(),
    }, warnings


def link_key(map_id: str, warp_id: int) -> str:
    return f"{map_id}:{warp_id}"


@dataclass
class Run:
    """Progreso de una partida concreta.

    visited  mapas pisados, con el momento de la primera vez
    links    puerta de origen -> puerta de destino. `return_seen` marca que
             tambien se ha recorrido en sentido contrario
    specials transiciones que no salen de un warp_event (agujeros, guiones,
             conexiones entre rutas): no son puertas, pero revelan mapa
    """

    name: str = "default"
    visited: dict[str, float] = field(default_factory=dict)
    links: dict[str, dict] = field(default_factory=dict)
    specials: list[dict] = field(default_factory=list)
    updated: float = 0.0

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ---- persistencia -------------------------------------------------

    @property
    def path(self) -> Path:
        return run_path(self.name)

    @classmethod
    def load(cls, name: str = "default") -> "Run":
        run = cls(name=name)
        if run.path.is_file():
            with open(run.path, encoding="utf-8") as fh:
                data = json.load(fh)
            run.visited = data.get("visited", {})
            run.links = data.get("links", {})
            run.specials = data.get("specials", [])
            run.updated = data.get("updated", 0.0)
        return run

    def save(self) -> None:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "name": self.name,
            "visited": self.visited,
            "links": self.links,
            "specials": self.specials,
            "updated": self.updated,
        }
        # Escritura atomica: un cierre a destiempo no debe dejar el fichero
        # de la partida a medias.
        temporary = self.path.with_suffix(".json.tmp")
        with open(temporary, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        temporary.replace(self.path)

    # ---- mutaciones ---------------------------------------------------

    def visit(self, map_id: str) -> bool:
        """Marca un mapa como pisado. Devuelve True si es la primera vez."""
        with self._lock:
            if map_id in self.visited:
                return False
            self.visited[map_id] = time.time()
            self.updated = time.time()
        self.save()
        return True

    def add_link(self, source: str, source_warp: int, dest: str, dest_warp: int) -> dict:
        """Registra que una puerta lleva a otra.

        Si ya se conocia el sentido contrario, el par pasa a confirmado en
        ambas direcciones.
        """
        with self._lock:
            key = link_key(source, source_warp)
            reverse = link_key(dest, dest_warp)
            entry = self.links.get(key)
            if entry is None:
                entry = {
                    "from_map": source, "from_warp": source_warp,
                    "to_map": dest, "to_warp": dest_warp,
                    "return_seen": False,
                    "first_seen": time.time(),
                }
                self.links[key] = entry

            back = self.links.get(reverse)
            if back and back["to_map"] == source and back["to_warp"] == source_warp:
                entry["return_seen"] = True
                back["return_seen"] = True
            self.updated = time.time()
        self.save()
        return entry

    def add_special(self, kind: str, source: str, dest: str, detail: dict | None = None) -> dict:
        """Registra una transicion que no viene de un warp_event."""
        with self._lock:
            entry = {
                "kind": kind, "from_map": source, "to_map": dest,
                "detail": detail or {}, "seen": time.time(),
            }
            # No repetir la misma transicion una y otra vez.
            for existing in self.specials:
                if (existing["kind"], existing["from_map"], existing["to_map"]) == \
                        (kind, source, dest):
                    return existing
            self.specials.append(entry)
            self.updated = time.time()
        self.save()
        return entry

    def switch_to(self, name: str) -> None:
        """Carga otra partida DENTRO de este mismo objeto.

        El tracker guarda una referencia a este Run (app/server.py), asi que
        reasignar la variable global lo dejaria escribiendo en la partida
        vieja. Se lee del disco antes de tocar nada para que un fichero
        ilegible no deje el estado a medias.
        """
        other = Run.load(safe_run_name(name))
        with self._lock:
            self.name = other.name
            self.visited = other.visited
            self.links = other.links
            self.specials = other.specials
            self.updated = other.updated

    def replace_with(self, content: dict) -> None:
        """Sustituye el contenido de la partida actual (importar)."""
        with self._lock:
            self.visited = content["visited"]
            self.links = content["links"]
            self.specials = content["specials"]
            self.updated = time.time()
        self.save()

    def reset(self) -> None:
        with self._lock:
            self.visited.clear()
            self.links.clear()
            self.specials.clear()
            self.updated = time.time()
        self.save()

    # ---- lectura ------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "visited": sorted(self.visited),
                "links": list(self.links.values()),
                "specials": list(self.specials),
                "updated": self.updated,
            }
