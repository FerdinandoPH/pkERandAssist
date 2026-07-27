"""Deduce que puerta lleva a que puerta a partir de lo que se lee del emulador.

El juego solo dice donde estas: mapa, casilla y por que warp entraste. La
puerta de *salida* no la dice nadie, asi que se deduce de la ultima casilla
que pisaste en el mapa anterior.

Toda la logica trabaja sobre `Sample`, sin tocar sockets, para poder probarla
reproduciendo trazas grabadas.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterable

# Margen al buscar la puerta de origen: al cruzar, la ultima muestra puede
# haberse tomado un instante antes de pisar la casilla exacta.
WARP_SEARCH_RADIUS = 1
# Cuantas POSICIONES DISTINTAS atras se mira dentro del mapa de origen. Se
# guardan posiciones y no muestras sueltas porque el fundido de una puerta dura
# mucho mas que el muestreo: repetir la misma casilla veinte veces echaba del
# historial la casilla de la puerta y la transicion se quedaba sin origen.
HISTORY_DEPTH = 12


@dataclass(frozen=True)
class Sample:
    map_group: int
    map_num: int
    warp_id: int
    x: int
    y: int
    frame: int = 0


@dataclass
class Transition:
    """Un cambio de sitio ya interpretado."""
    kind: str               # "warp" | "connection" | "tile" | "script"
    from_map: str | None
    from_warp: int | None
    to_map: str
    to_warp: int | None
    detail: dict


class Tracker:
    def __init__(
        self,
        maps: list[dict],
        warps: dict[str, list[dict]],
        warp_tiles: dict[str, dict[str, str]] | None = None,
        on_event: Callable[[dict], None] | None = None,
        run=None,
    ) -> None:
        self.by_index = {(m["map_group"], m["map_num"]): m["id"] for m in maps}
        self.maps = {m["id"]: m for m in maps}
        self.warps = warps
        self.warp_tiles = warp_tiles or {}
        self.on_event = on_event
        self.run = run

        self.history: deque[tuple[str, Sample]] = deque(maxlen=HISTORY_DEPTH)
        self.current: Sample | None = None
        self.current_map: str | None = None

    # ---- consultas ----------------------------------------------------

    def map_id_for(self, sample: Sample) -> str | None:
        return self.by_index.get((sample.map_group, sample.map_num))

    def warp_at(self, map_id: str, x: int, y: int) -> int | None:
        """Indice del warp que hay en esa casilla (o pegado a ella)."""
        candidates = self.warps.get(map_id) or []
        best: tuple[int, int] | None = None
        for index, warp in enumerate(candidates):
            distance = abs(warp["x"] - x) + abs(warp["y"] - y)
            if distance <= WARP_SEARCH_RADIUS and (best is None or distance < best[0]):
                best = (distance, index)
        return best[1] if best else None

    def behavior_at(self, map_id: str, x: int, y: int) -> str | None:
        """Comportamiento del metatile pisado, si es de los que teletransportan."""
        entry = self.maps.get(map_id)
        if entry is None:
            return None
        return (self.warp_tiles.get(entry["layout"]) or {}).get(f"{x},{y}")

    def _connects_to(self, from_map: str, to_map: str) -> bool:
        entry = self.maps.get(from_map)
        if entry is None:
            return False
        return any(c["map"] == to_map for c in entry["connections"])

    def _find_exit(self, from_map: str) -> tuple[int | None, Sample | None]:
        """Busca hacia atras la ultima casilla del mapa de origen con puerta."""
        fallback: Sample | None = None
        for map_id, sample in reversed(self.history):
            if map_id != from_map:
                break
            if fallback is None:
                fallback = sample
            found = self.warp_at(from_map, sample.x, sample.y)
            if found is not None:
                return found, sample
        return None, fallback

    # ---- nucleo -------------------------------------------------------

    def feed(self, sample: Sample) -> list[dict]:
        """Procesa una lectura del emulador y devuelve los eventos que genera."""
        map_id = self.map_id_for(sample)
        if map_id is None:
            return []  # indice de mapa que no conocemos: ignorar la lectura

        events: list[dict] = []
        previous, previous_map = self.current, self.current_map

        if previous is not None and previous_map is not None:
            transition = self._detect(previous, previous_map, sample, map_id)
            if transition is not None:
                events.extend(self._record(transition))

        if self.run is not None and self.run.visit(map_id):
            events.append({"type": "visit", "map": map_id})

        self._remember(map_id, sample)
        self.current, self.current_map = sample, map_id

        events.append({
            "type": "player", "map": map_id,
            "x": sample.x, "y": sample.y, "warp": sample.warp_id,
        })
        for event in events:
            if self.on_event is not None:
                self.on_event(event)
        return events

    def _remember(self, map_id: str, sample: Sample) -> None:
        """Anota la posicion en el historial, sin repetir la ultima.

        Estar quieto (o esperar a que termine un fundido) manda decenas de
        muestras identicas. Si cada una ocupara sitio, doce muestras dejarian
        de ser doce pasos y la casilla por la que se salio quedaria fuera del
        alcance de `_find_exit`.
        """
        if self.history:
            last_map, last = self.history[-1]
            if last_map == map_id and (last.x, last.y) == (sample.x, sample.y):
                return
        self.history.append((map_id, sample))

    def forget_history(self) -> None:
        """Olvida por donde ibas. Se llama al cambiar de partida.

        El historial pertenece a la partida anterior: comparar la ultima
        lectura de una con la primera de otra inventaria una transicion que no
        ha ocurrido.
        """
        self.history.clear()
        self.current = None
        self.current_map = None

    def last_player(self) -> dict | None:
        """Ultima posicion conocida, con la misma forma que el evento player.

        Sirve para que recargar la pagina en mitad de una partida no borre el
        marcador ni el "ahora mismo" hasta la siguiente lectura.
        """
        if self.current is None or self.current_map is None:
            return None
        return {
            "type": "player", "map": self.current_map,
            "x": self.current.x, "y": self.current.y,
            "warp": self.current.warp_id,
        }

    def _detect(
        self, previous: Sample, previous_map: str, sample: Sample, map_id: str
    ) -> Transition | None:
        """Decide si entre dos muestras ha habido un cambio de sitio."""
        changed_map = map_id != previous_map
        changed_warp = sample.warp_id != previous.warp_id

        # Quedarse en el mismo mapa con el mismo warp_id no es cambiar de
        # sitio, por lejos que aparezca el jugador. El juego apunta por que
        # warp se ha entrado, asi que sin cambio de warp_id no ha habido
        # puerta: ese salto es el bloque de guardado poniendose al dia durante
        # el fundido (trae ya la posicion de destino con el mapa todavia sin
        # cambiar) o un hueco en el muestreo. Tomarlo por una puerta inventaba
        # un enlace del mapa consigo mismo que ademas tapaba el de verdad. Los
        # teletransportes del gimnasio de Algaria si cambian el warp_id.
        if not (changed_map or changed_warp):
            return None

        from_warp, exit_sample = self._find_exit(previous_map)
        exit_sample = exit_sample or previous
        connection = changed_map and self._connects_to(previous_map, map_id)
        to_warp = sample.warp_id
        if to_warp is not None and not (0 <= to_warp < len(self.warps.get(map_id) or [])):
            to_warp = None
        if from_warp is not None and to_warp is None and not connection:
            # Destino sin warp_id utilizable (los warps dinamicos lo dejan en
            # -1): habiendo salido por una puerta de verdad, la casilla en la
            # que aparece el jugador dice a que puerta ha llegado.
            to_warp = self.warp_at(map_id, sample.x, sample.y)

        if from_warp is not None and to_warp is not None:
            # Una puerta no puede llevar a su propia casilla: si sale eso, lo
            # que hemos visto no es un warp sino un hueco en el muestreo.
            if previous_map == map_id and from_warp == to_warp:
                return None
            return Transition("warp", previous_map, from_warp, map_id, to_warp, {})

        # Sin puerta de origen: hay que averiguar por que te has movido.
        behavior = self.behavior_at(previous_map, exit_sample.x, exit_sample.y)
        if connection:
            kind = "connection"
        elif behavior is not None:
            kind = "tile"
        else:
            kind = "script"

        return Transition(
            kind, previous_map, from_warp, map_id, to_warp,
            {"behavior": behavior, "from_x": exit_sample.x, "from_y": exit_sample.y},
        )

    def _record(self, transition: Transition) -> list[dict]:
        events: list[dict] = []
        if transition.kind == "warp" and self.run is not None:
            link = self.run.add_link(
                transition.from_map, transition.from_warp,
                transition.to_map, transition.to_warp,
            )
            events.append({"type": "link", "link": link})
        elif self.run is not None:
            special = self.run.add_special(
                transition.kind, transition.from_map, transition.to_map, transition.detail
            )
            events.append({"type": "special", "special": special})
        return events

    # ---- utilidades ---------------------------------------------------

    def replay(self, samples: Iterable[Sample]) -> list[dict]:
        """Reproduce una traza entera; usado por los tests."""
        events: list[dict] = []
        for sample in samples:
            events.extend(self.feed(sample))
        return events

    def describe(self, transition_event: dict) -> str:
        """Texto legible de un evento, para la consola."""
        if transition_event["type"] == "link":
            link = transition_event["link"]
            origin = self.maps.get(link["from_map"], {}).get("name", link["from_map"])
            target = self.maps.get(link["to_map"], {}).get("name", link["to_map"])
            arrow = "<->" if link["return_seen"] else "->"
            return (f"{origin} puerta {link['from_warp']} {arrow} "
                    f"{target} puerta {link['to_warp']}")
        if transition_event["type"] == "special":
            special = transition_event["special"]
            origin = self.maps.get(special["from_map"], {}).get("name", special["from_map"])
            target = self.maps.get(special["to_map"], {}).get("name", special["to_map"])
            detail = special["detail"].get("behavior") or special["kind"]
            return f"{origin} => {target}  ({detail})"
        if transition_event["type"] == "visit":
            name = self.maps.get(transition_event["map"], {}).get("name", transition_event["map"])
            return f"nuevo mapa: {name}"
        return ""
