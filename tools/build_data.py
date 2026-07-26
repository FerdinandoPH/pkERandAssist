"""Extrae de pret/pokeemerald los datos estaticos que necesita el asistente.

Genera en data/static/:
  maps.json            mapas indexados por (map_group, map_num), que es lo que
                       aparece en la RAM del juego
  warps.json           posiciones de cada warp; el indice ES el warpId
  warps_vanilla.json   destinos originales, SOLO para depuracion (spoilers)
  layouts.json         dimensiones, tilesets y rutas de blockdata
  tilesets.json        rutas de assets y flag isSecondary
  metatile_behaviors.json  id -> nombre MB_*, y cuales implican transicion

Uso:
    python tools/build_data.py [--pokeemerald ../pokeemerald]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, load_json, resolve_pokeemerald, write_json  # noqa: E402
from naming import humanize, load_overrides, mapsec_label  # noqa: E402

# Behaviors que provocan (o pueden provocar) un cambio de mapa. El tracker los
# usa cuando la casilla pisada no corresponde a ningun warp_event: agujeros del
# suelo, escaleras mecanicas y warps por script no figuran en la lista de warps.
TRANSITION_BEHAVIORS = {
    "MB_ANIMATED_DOOR", "MB_NON_ANIMATED_DOOR", "MB_WATER_DOOR",
    "MB_CLOSED_SOOTOPOLIS_DOOR", "MB_PETALBURG_GYM_DOOR",
    "MB_TRICK_HOUSE_PUZZLE_DOOR", "MB_SKY_PILLAR_CLOSED_DOOR",
    "MB_SECRET_BASE_BREAKABLE_DOOR",
    "MB_LADDER", "MB_UP_ESCALATOR", "MB_DOWN_ESCALATOR",
    "MB_CRACKED_FLOOR_HOLE", "MB_MT_PYRE_HOLE", "MB_SECRET_BASE_HOLE",
    "MB_EAST_ARROW_WARP", "MB_WEST_ARROW_WARP", "MB_NORTH_ARROW_WARP",
    "MB_SOUTH_ARROW_WARP", "MB_WATER_SOUTH_ARROW_WARP", "MB_DEEP_SOUTH_WARP",
    "MB_AQUA_HIDEOUT_WARP", "MB_MOSSDEEP_GYM_WARP", "MB_BATTLE_PYRAMID_WARP",
    "MB_LAVARIDGE_GYM_1F_WARP", "MB_LAVARIDGE_GYM_B1F_WARP",
    "MB_STAIRS_OUTSIDE_ABANDONED_SHIP", "MB_SHOAL_CAVE_ENTRANCE",
}


def parse_map_groups(pe: Path) -> list[tuple[int, int, str]]:
    """Devuelve (map_group, map_num, nombre) para cada mapa.

    map_group es el indice del grupo en `group_order` y map_num la posicion
    dentro de ese grupo: exactamente los dos bytes que el juego guarda en
    gSaveBlock1Ptr->location.
    """
    groups = load_json(pe / "data" / "maps" / "map_groups.json")
    out: list[tuple[int, int, str]] = []
    for group_index, group_key in enumerate(groups["group_order"]):
        for map_num, map_name in enumerate(groups[group_key]):
            out.append((group_index, map_num, map_name))
    return out


def parse_tilesets(pe: Path) -> dict[str, dict]:
    """Cruza headers.h (isSecondary + simbolo de metatiles) con metatiles.h.

    El nombre del tileset no siempre coincide con el de sus metatiles
    (gTileset_Building usa gMetatiles_InsideBuilding), asi que hay que seguir
    el campo `.metatiles` del header en vez de derivarlo del nombre.
    """
    tileset_dir = pe / "src" / "data" / "tilesets"
    headers = (tileset_dir / "headers.h").read_text(encoding="utf-8")
    metatiles = (tileset_dir / "metatiles.h").read_text(encoding="utf-8")
    # Los secundarios estan en graphics.h, pero los primarios (general,
    # building, secret_base) se declaran en src/graphics.c.
    graphics = "\n".join(
        (pe / rel).read_text(encoding="utf-8")
        for rel in ("src/data/tilesets/graphics.h", "src/graphics.c")
    )

    bins: dict[str, str] = dict(re.findall(
        r"const u16 (gMetatile\w+)\[\]\s*=\s*INCBIN_U16\(\"([^\"]+)\"\)", metatiles
    ))
    # Los tiles pueden declararse comprimidos o no; el header referencia el
    # simbolo sin el sufijo, asi que se indexa por ambos.
    tiles: dict[str, str] = {}
    for symbol, path in re.findall(
        r"const u\d+ (gTilesetTiles_\w+)\[\]\s*=\s*INCGFX_U\d+\(\"([^\"]+)\"", graphics
    ):
        tiles[symbol] = path
        tiles.setdefault(symbol.removesuffix("Compressed"), path)
    # De cada bloque de paletas basta la primera para saber la carpeta.
    palettes: dict[str, str] = {}
    for symbol, body in re.findall(
        r"const u16 (gTilesetPalettes_\w+)\[\]\[16\]\s*=\s*\{(.*?)\};", graphics, re.S
    ):
        first = re.search(r"INCGFX_U16\(\"([^\"]+)\"", body)
        if first:
            palettes[symbol] = str(Path(first.group(1)).parent).replace("\\", "/")

    def field(body: str, name: str) -> str | None:
        found = re.search(rf"\.{name}\s*=\s*(\w+)", body)
        return found.group(1) if found else None

    tilesets: dict[str, dict] = {}
    for name, body in re.findall(
        r"const struct Tileset (gTileset_\w+)\s*=\s*\{(.*?)\};", headers, re.S
    ):
        paths = {
            "tiles": tiles.get(field(body, "tiles") or ""),
            "palettes": palettes.get(field(body, "palettes") or ""),
            "metatiles": bins.get(field(body, "metatiles") or ""),
            "attributes": bins.get(field(body, "metatileAttributes") or ""),
        }
        if any(v is None for v in paths.values()):
            continue  # tileset sin assets (los gTileset_Unused* de relleno)
        tilesets[name] = {
            "is_secondary": field(body, "isSecondary") == "TRUE",
            **paths,
        }
    return tilesets


def parse_behaviors(pe: Path) -> list[str]:
    """Lee el enum MetatileBehavior: el indice de cada entrada es su valor."""
    text = (pe / "include" / "constants" / "metatile_behaviors.h").read_text(encoding="utf-8")
    # El enum es anonimo en pokeemerald; el fichero solo contiene ese.
    body = re.search(r"enum\s*\w*\s*\{(.*?)\}\s*;", text, re.S)
    if not body:
        raise SystemExit("No pude leer el enum de metatile behaviors")
    names: list[str] = []
    for line in body.group(1).splitlines():
        line = re.sub(r"//.*", "", line).strip().rstrip(",").strip()
        if not line:
            continue
        if "=" in line:  # ninguna entrada del enum vanilla lo usa, pero por si acaso
            name, _, value = (p.strip() for p in line.partition("="))
            index = int(value, 0)
            while len(names) < index:
                names.append(f"MB_UNKNOWN_{len(names)}")
            names.append(name)
        else:
            names.append(line)
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pokeemerald", help="ruta al clon de pret/pokeemerald")
    args = parser.parse_args()
    pe = resolve_pokeemerald(args.pokeemerald)

    overrides = load_overrides(DATA_DIR.parent / "i18n" / "es_overrides.json")

    maps: list[dict] = []
    warps: dict[str, list[dict]] = {}
    warps_vanilla: dict[str, list[dict]] = {}
    problems: list[str] = []

    for group, num, folder in parse_map_groups(pe):
        map_json = pe / "data" / "maps" / folder / "map.json"
        if not map_json.is_file():
            problems.append(f"falta {map_json}")
            continue
        data = load_json(map_json)
        map_id = data["id"]
        mapsec = data.get("region_map_section", "MAPSEC_NONE")

        # El nombre del mapa suele empezar por el de su zona; si esa zona esta
        # traducida, se traduce tambien ahi para no mezclar idiomas dentro de
        # la misma linea ("Mossdeep City - Gym" junto a "Ciudad Algaria").
        english_zone = mapsec_label(mapsec)
        zone_name = overrides.get(mapsec, english_zone)
        map_name = overrides.get(map_id)
        if map_name is None:
            map_name = humanize(folder)
            if zone_name != english_zone and map_name.startswith(english_zone):
                map_name = zone_name + map_name[len(english_zone):]

        maps.append({
            "id": map_id,
            "folder": folder,
            "map_group": group,
            "map_num": num,
            "layout": data["layout"],
            "mapsec": mapsec,
            "map_type": data.get("map_type", "MAP_TYPE_NONE"),
            "connections": data.get("connections") or [],
            "name": map_name,
            "mapsec_name": zone_name,
        })

        events = data.get("warp_events") or []
        # El indice en esta lista es el warpId que el juego escribe en RAM.
        warps[map_id] = [
            {"x": w["x"], "y": w["y"], "elevation": w.get("elevation", 0)}
            for w in events
        ]
        warps_vanilla[map_id] = [
            {"dest_map": w.get("dest_map"), "dest_warp_id": w.get("dest_warp_id")}
            for w in events
        ]

    layouts = {
        entry["id"]: {
            "name": entry["name"],
            "width": entry["width"],
            "height": entry["height"],
            "primary_tileset": entry["primary_tileset"],
            "secondary_tileset": entry["secondary_tileset"],
            "blockdata": entry["blockdata_filepath"],
            "border": entry["border_filepath"],
        }
        for entry in load_json(pe / "data" / "layouts" / "layouts.json")["layouts"]
    }

    behaviors = parse_behaviors(pe)
    tilesets = parse_tilesets(pe)

    # Coherencia: todo mapa debe apuntar a un layout existente, y todo layout a
    # tilesets con assets en disco. Si algo de esto falla, el render se cae.
    for entry in maps:
        if entry["layout"] not in layouts:
            problems.append(f"{entry['id']}: layout desconocido {entry['layout']}")
    for layout_id, layout in layouts.items():
        for slot in ("primary_tileset", "secondary_tileset"):
            name = layout[slot]
            if name in ("0", "NULL", None):
                continue  # layout sin tileset secundario
            if name not in tilesets:
                problems.append(f"{layout_id}: {slot} sin assets ({name})")
                continue
            missing = [
                key for key in ("tiles", "metatiles", "attributes")
                if not (pe / tilesets[name][key]).is_file()
            ]
            if missing:
                problems.append(f"{name}: faltan ficheros {missing}")
    problems = sorted(set(problems))

    write_json(DATA_DIR / "maps.json", {"maps": maps})
    write_json(DATA_DIR / "warps.json", warps)
    write_json(DATA_DIR / "warps_vanilla.json", warps_vanilla)
    write_json(DATA_DIR / "layouts.json", layouts)
    write_json(DATA_DIR / "tilesets.json", tilesets)
    write_json(DATA_DIR / "metatile_behaviors.json", {
        "names": behaviors,
        "transition_ids": sorted(
            i for i, n in enumerate(behaviors) if n in TRANSITION_BEHAVIORS
        ),
    })

    total_warps = sum(len(v) for v in warps.values())
    print(f"mapas:      {len(maps)}")
    print(f"warps:      {total_warps}")
    print(f"layouts:    {len(layouts)}")
    print(f"tilesets:   {len(tilesets)}")
    print(f"behaviors:  {len(behaviors)} "
          f"({len([n for n in behaviors if n in TRANSITION_BEHAVIORS])} de transicion)")

    unknown = TRANSITION_BEHAVIORS - set(behaviors)
    if unknown:
        problems.append(f"behaviors declarados que no existen en el enum: {sorted(unknown)}")

    if problems:
        print("\nIncidencias:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"\nEscrito en {DATA_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
