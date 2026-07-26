"""Estado de una partida: que has pisado y que puertas has confirmado.

Se guarda en runs/<nombre>.json despues de cada cambio, para que cerrar la
aplicacion (o el emulador) no pierda nada.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


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
        return RUNS_DIR / f"{self.name}.json"

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
