"""Calcula la posicion de cada mapa dentro del lienzo unico.

Los exteriores se ensamblan siguiendo las `connections` de cada mapa, que dan
la geografia real de Hoenn. Los interiores no tienen posicion propia, asi que
se agrupan por zona (region_map_section) y se empaquetan en una banda lateral,
ordenada de norte a sur como las columnas de pokemoncompletion.

Genera data/static/world_layout.json con todo en pixeles.

Uso:
    python tools/build_layout.py
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict, deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, load_json, write_json  # noqa: E402

TILE = 16  # pixeles por metatile

# Mapas que tienen sitio propio en la geografia de la region.
OUTDOOR_TYPES = {
    "MAP_TYPE_TOWN", "MAP_TYPE_CITY", "MAP_TYPE_ROUTE",
    "MAP_TYPE_OCEAN_ROUTE", "MAP_TYPE_UNDERWATER",
}
# `dive` y `emerge` conectan superficie y fondo marino: no son adyacencia.
SPATIAL_DIRECTIONS = {"up", "down", "left", "right"}

GAP = 4              # separacion entre mapas, en metatiles
COMPONENT_GAP = 12   # separacion entre componentes desconectados
SECTION_GAP = 10     # separacion entre secciones de interiores
LABEL_HEIGHT = 3     # alto reservado para el rotulo de cada seccion
BAND_WIDTH = 220     # ancho de la banda de interiores, en metatiles


def offset_for(direction: str, origin: dict, target: dict, offset: int) -> tuple[int, int]:
    """Posicion relativa de `target` respecto de la esquina de `origin`."""
    if direction == "up":
        return offset, -target["height"]
    if direction == "down":
        return offset, origin["height"]
    if direction == "left":
        return -target["width"], offset
    if direction == "right":
        return origin["width"], offset
    raise ValueError(direction)


def assemble_outdoors(maps: dict[str, dict]) -> tuple[dict[str, tuple[int, int]], list[list[str]], list[str]]:
    """BFS por `connections`; devuelve posiciones, componentes e incoherencias."""
    outdoors = [m for m in maps.values() if m["map_type"] in OUTDOOR_TYPES]
    positions: dict[str, tuple[int, int]] = {}
    components: list[list[str]] = []
    problems: list[str] = []

    # Empezar por Pueblo Escaso deja el continente como primer componente.
    order = sorted(outdoors, key=lambda m: (m["id"] != "MAP_LITTLEROOT_TOWN", m["id"]))

    for root in order:
        if root["id"] in positions:
            continue
        positions[root["id"]] = (0, 0)
        component = [root["id"]]
        queue = deque([root["id"]])

        while queue:
            current_id = queue.popleft()
            current = maps[current_id]
            cx, cy = positions[current_id]
            for connection in current["connections"]:
                direction = connection["direction"]
                if direction not in SPATIAL_DIRECTIONS:
                    continue
                other_id = connection["map"]
                other = maps.get(other_id)
                if other is None or other["map_type"] not in OUTDOOR_TYPES:
                    continue
                dx, dy = offset_for(direction, current, other, connection["offset"])
                target = (cx + dx, cy + dy)
                if other_id in positions:
                    if positions[other_id] != target:
                        problems.append(
                            f"{current_id} -> {other_id} ({direction}): "
                            f"{positions[other_id]} vs {target}"
                        )
                    continue
                positions[other_id] = target
                component.append(other_id)
                queue.append(other_id)

        components.append(component)

    return positions, components, problems


def shelf_pack(
    items: list[tuple[str, int, int]],
    band_width: int,
    *,
    keep_order: bool = False,
) -> tuple[dict[str, tuple[int, int]], int, int]:
    """Empaqueta (id, w, h) en estanterias.

    Devuelve las posiciones y el ancho y alto realmente ocupados. Por defecto
    coloca primero lo mas alto, que compacta mejor; con `keep_order` respeta el
    orden recibido, para no romper una ordenacion con significado.
    """
    if not keep_order:
        items = sorted(items, key=lambda i: (-i[2], -i[1], i[0]))
    placed: dict[str, tuple[int, int]] = {}
    x = y = shelf_height = used_width = 0
    for item_id, width, height in items:
        if x and x + width > band_width:
            x = 0
            y += shelf_height + GAP
            shelf_height = 0
        placed[item_id] = (x, y)
        x += width + GAP
        used_width = max(used_width, x - GAP)
        shelf_height = max(shelf_height, height)
    return placed, used_width, y + shelf_height


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--band-width", type=int, default=BAND_WIDTH,
                        help="ancho de la banda de interiores, en metatiles")
    args = parser.parse_args(argv)

    maps = {m["id"]: m for m in load_json(DATA_DIR / "maps.json")["maps"]}
    layouts = load_json(DATA_DIR / "layouts.json")

    # Las dimensiones vienen del layout, no del mapa.
    for entry in maps.values():
        layout = layouts[entry["layout"]]
        entry["width"] = layout["width"]
        entry["height"] = layout["height"]

    positions, components, problems = assemble_outdoors(maps)

    # El componente mas grande es el continente y manda en el lienzo; el resto
    # (islas sueltas y las zonas submarinas) se empaquetan en una banda debajo,
    # porque apilarlos de uno en uno desperdicia una altura enorme.
    components.sort(key=lambda c: -sum(maps[m]["width"] * maps[m]["height"] for m in c))
    placements: dict[str, dict] = {}

    boxes = []
    for index, component in enumerate(components):
        min_x = min(positions[m][0] for m in component)
        min_y = min(positions[m][1] for m in component)
        max_x = max(positions[m][0] + maps[m]["width"] for m in component)
        max_y = max(positions[m][1] + maps[m]["height"] for m in component)
        boxes.append({
            "index": index, "members": component,
            "min_x": min_x, "min_y": min_y,
            "width": max_x - min_x, "height": max_y - min_y,
        })

    continent, others = boxes[0], boxes[1:]
    continent_right = continent["width"]
    origins = {continent["index"]: (0, 0)}

    packed, _, band_height = shelf_pack(
        [(str(b["index"]), b["width"], b["height"]) for b in others],
        max(continent_right, 1),
    )
    island_top = continent["height"] + COMPONENT_GAP
    for box in others:
        dx, dy = packed[str(box["index"])]
        origins[box["index"]] = (dx, island_top + dy)

    for box in boxes:
        origin_x, origin_y = origins[box["index"]]
        for map_id in box["members"]:
            x = positions[map_id][0] - box["min_x"] + origin_x
            y = positions[map_id][1] - box["min_y"] + origin_y
            placements[map_id] = {
                "x": x * TILE, "y": y * TILE,
                "w": maps[map_id]["width"] * TILE,
                "h": maps[map_id]["height"] * TILE,
                "layout": maps[map_id]["layout"],
                "kind": "outdoor",
            }

    outdoor_bottom = island_top + band_height if others else continent["height"]

    # Interiores: agrupados por zona y ordenados de norte a sur segun donde
    # este esa zona en el mapa, para que la banda siga la geografia.
    indoors: dict[str, list[str]] = defaultdict(list)
    for entry in maps.values():
        if entry["map_type"] not in OUTDOOR_TYPES:
            indoors[entry["mapsec"]].append(entry["id"])

    zone_anchor: dict[str, tuple[int, int]] = {}
    for entry in maps.values():
        if entry["id"] in placements and entry["map_type"] in OUTDOOR_TYPES:
            anchor = (placements[entry["id"]]["y"], placements[entry["id"]]["x"])
            current = zone_anchor.get(entry["mapsec"])
            if current is None or anchor < current:
                zone_anchor[entry["mapsec"]] = anchor

    # Doble empaquetado: primero los interiores dentro del bloque de su zona,
    # despues los bloques entre si. Asi cada zona ocupa solo lo que necesita y
    # la banda queda como un mosaico en vez de una tira infinita.
    ordered_zones = sorted(
        indoors, key=lambda z: (zone_anchor.get(z) is None, zone_anchor.get(z, (0, 0)), z)
    )
    blocks: dict[str, dict] = {}
    for mapsec in ordered_zones:
        members = indoors[mapsec]
        items = [(m, maps[m]["width"], maps[m]["height"]) for m in members]
        packed, used_width, height = shelf_pack(items, args.band_width)
        blocks[mapsec] = {
            "members": packed,
            "w": max(used_width, len(maps[members[0]]["mapsec_name"])),
            "h": LABEL_HEIGHT + height,
        }

    band_x = continent_right + COMPONENT_GAP
    band_width = max(continent_right, args.band_width)
    section_positions, _, _ = shelf_pack(
        [(z, blocks[z]["w"] + SECTION_GAP, blocks[z]["h"] + SECTION_GAP)
         for z in ordered_zones],
        band_width,
        keep_order=True,
    )

    sections: list[dict] = []
    for mapsec in ordered_zones:
        block = blocks[mapsec]
        section_x, section_y = section_positions[mapsec]
        top = section_y + LABEL_HEIGHT
        for map_id, (dx, dy) in block["members"].items():
            placements[map_id] = {
                "x": (band_x + section_x + dx) * TILE, "y": (top + dy) * TILE,
                "w": maps[map_id]["width"] * TILE,
                "h": maps[map_id]["height"] * TILE,
                "layout": maps[map_id]["layout"],
                "kind": "indoor",
            }
        sections.append({
            "mapsec": mapsec,
            "label": maps[indoors[mapsec][0]]["mapsec_name"],
            "x": (band_x + section_x) * TILE, "y": section_y * TILE,
            "w": block["w"] * TILE, "h": block["h"] * TILE,
        })

    width = max(p["x"] + p["w"] for p in placements.values())
    height = max(p["y"] + p["h"] for p in placements.values())

    # Ningun mapa debe pisar a otro. Se exceptuan los pares que estan
    # conectados entre si: en los datos originales unas pocas conexiones no son
    # simetricas (Verdanturf/Ruta 116 y dos mas discrepan en 2 metatiles), asi
    # que ahi el solape es del juego, no del empaquetado.
    connected = {
        frozenset((entry["id"], connection["map"]))
        for entry in maps.values()
        for connection in entry["connections"]
    }
    overlaps = find_overlaps(placements)
    expected = [pair for pair in overlaps if frozenset(pair) in connected]
    unexpected = [pair for pair in overlaps if frozenset(pair) not in connected]

    write_json(DATA_DIR / "world_layout.json", {
        "tile_size": TILE,
        "width": width,
        "height": height,
        "outdoor_height": outdoor_bottom * TILE,
        "band_x": band_x * TILE,
        "sections": sections,
        "placements": placements,
    }, compact=True)

    print(f"mapas colocados:   {len(placements)}")
    print(f"componentes:       {len(components)} "
          f"(el mayor con {len(components[0])} mapas)")
    print(f"zonas interiores:  {len(sections)}")
    print(f"lienzo:            {width} x {height} px")
    print(f"solapes:           {len(unexpected)} "
          f"({len(expected)} entre mapas conectados, del propio juego)")

    if problems:
        print(f"\nConexiones asimetricas en los datos originales ({len(problems)}):")
        for p in problems:
            print(f"  - {p}")
    if unexpected:
        print("\nSolapes inesperados:", file=sys.stderr)
        for a, b in unexpected[:10]:
            print(f"  - {a} / {b}", file=sys.stderr)
        return 1
    return 0


def find_overlaps(placements: dict[str, dict]) -> list[tuple[str, str]]:
    """Comprueba solapes por barrido de linea sobre el eje X."""
    boxes = sorted(
        ((p["x"], p["x"] + p["w"], p["y"], p["y"] + p["h"], map_id)
         for map_id, p in placements.items()),
        key=lambda b: b[0],
    )
    found: list[tuple[str, str]] = []
    active: list[tuple] = []
    for box in boxes:
        x0, x1, y0, y1, map_id = box
        active = [a for a in active if a[1] > x0]
        for other in active:
            if y0 < other[3] and other[2] < y1:
                found.append((map_id, other[4]))
        active.append(box)
    return found


if __name__ == "__main__":
    raise SystemExit(main())
