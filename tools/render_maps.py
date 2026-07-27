"""Renderiza cada layout de pokeemerald a PNG, con mipmaps.

Un metatile son 16x16 px compuestos por 8 tiles de 8x8: cuatro de capa inferior
y cuatro de capa superior, cada uno con su tile id, sus flips y su paleta. El
indice 0 de cada paleta es el color transparente.

Genera en assets/layouts/:
  <LAYOUT_ID>.png      resolucion nativa (16 px por metatile)
  <LAYOUT_ID>.4.png    un cuarto
  <LAYOUT_ID>.16.png   un dieciseisavo

y en data/static/warp_tiles.json las casillas cuyo metatile implica una
transicion (puertas, escaleras, agujeros), que el tracker usa cuando la casilla
pisada no corresponde a ningun warp_event.

Uso:
    python tools/render_maps.py [--pokeemerald ../pokeemerald] [--only LAYOUT_ID]
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import ASSETS_DIR, DATA_DIR, load_json, resolve_pokeemerald, write_json  # noqa: E402

TILES_PER_ROW = 16
NUM_TILES_IN_PRIMARY = 512
NUM_METATILES_IN_PRIMARY = 512
NUM_PALS_IN_PRIMARY = 6
NUM_METATILES_TOTAL = 1024

METATILE_ID_MASK = 0x03FF
TILE_ID_MASK = 0x03FF
FLIP_X = 0x0400
FLIP_Y = 0x0800
BEHAVIOR_MASK = 0x00FF

MIPMAPS = (4, 16)


@dataclass
class Tileset:
    name: str
    tiles: np.ndarray        # (n_tiles, 8, 8) indices de paleta
    palettes: np.ndarray     # (16, 16, 3) RGB
    metatiles: np.ndarray    # (n_metatiles, 8) uint16
    attributes: np.ndarray   # (n_metatiles,) uint16


def read_palette(path: Path) -> np.ndarray:
    """Lee un JASC-PAL de 16 colores."""
    lines = path.read_text(encoding="utf-8").splitlines()
    colors = []
    for line in lines[3:]:
        line = line.strip()
        if not line:
            continue
        colors.append([int(v) for v in line.split()[:3]])
    while len(colors) < 16:
        colors.append([0, 0, 0])
    return np.array(colors[:16], dtype=np.uint8)


def load_tileset(pe: Path, name: str, info: dict) -> Tileset:
    image = Image.open(pe / info["tiles"])
    if image.mode != "P":
        image = image.convert("P")
    indices = np.array(image, dtype=np.uint8)
    rows, cols = indices.shape[0] // 8, indices.shape[1] // 8
    # (rows, 8, cols, 8) -> (rows*cols, 8, 8), en orden de lectura
    tiles = (indices[: rows * 8, : cols * 8]
             .reshape(rows, 8, cols, 8)
             .transpose(0, 2, 1, 3)
             .reshape(rows * cols, 8, 8))

    palettes = np.zeros((16, 16, 3), dtype=np.uint8)
    pal_dir = pe / info["palettes"]
    for slot in range(16):
        pal_file = pal_dir / f"{slot:02}.pal"
        if pal_file.is_file():
            palettes[slot] = read_palette(pal_file)

    metatiles = np.fromfile(pe / info["metatiles"], dtype="<u2").reshape(-1, 8)
    attributes = np.fromfile(pe / info["attributes"], dtype="<u2")
    return Tileset(name, tiles, palettes, metatiles, attributes)


def _tile_pixels(primary: Tileset, secondary: Tileset | None, entry: int) -> np.ndarray | None:
    """Devuelve el tile de 8x8 en RGBA ya con paleta y flips aplicados."""
    tile_id = entry & TILE_ID_MASK
    palette_index = (entry >> 12) & 0xF

    if tile_id < NUM_TILES_IN_PRIMARY:
        source, local = primary, tile_id
    else:
        source, local = secondary, tile_id - NUM_TILES_IN_PRIMARY
    if source is None or local >= len(source.tiles):
        return None

    pixels = source.tiles[local]
    if entry & FLIP_X:
        pixels = pixels[:, ::-1]
    if entry & FLIP_Y:
        pixels = pixels[::-1, :]

    # Las paletas 0-5 vienen del tileset primario y las 6-12 del secundario,
    # que guarda cada una en el fichero con el numero de su ranura.
    if palette_index < NUM_PALS_IN_PRIMARY or secondary is None:
        palette = primary.palettes[palette_index]
    else:
        palette = secondary.palettes[palette_index]

    rgba = np.zeros((8, 8, 4), dtype=np.uint8)
    rgba[..., :3] = palette[pixels]
    rgba[..., 3] = np.where(pixels == 0, 0, 255)
    return rgba


def build_atlas(primary: Tileset, secondary: Tileset | None) -> np.ndarray:
    """Pre-renderiza los 1024 metatiles del par de tilesets a (1024, 16, 16, 4)."""
    atlas = np.zeros((NUM_METATILES_TOTAL, 16, 16, 4), dtype=np.uint8)
    for metatile_id in range(NUM_METATILES_TOTAL):
        if metatile_id < NUM_METATILES_IN_PRIMARY:
            source, local = primary, metatile_id
        else:
            source, local = secondary, metatile_id - NUM_METATILES_IN_PRIMARY
        if source is None or local >= len(source.metatiles):
            continue

        cell = atlas[metatile_id]
        for slot in range(8):  # 0-3 capa inferior, 4-7 capa superior
            tile = _tile_pixels(primary, secondary, int(source.metatiles[local, slot]))
            if tile is None:
                continue
            quadrant = slot % 4
            y0, x0 = (quadrant // 2) * 8, (quadrant % 2) * 8
            target = cell[y0:y0 + 8, x0:x0 + 8]
            mask = tile[..., 3] > 0
            target[mask] = tile[mask]
    return atlas


def build_behavior_table(primary: Tileset, secondary: Tileset | None) -> np.ndarray:
    """behavior de cada uno de los 1024 metatiles del par."""
    table = np.zeros(NUM_METATILES_TOTAL, dtype=np.uint16)
    n = min(len(primary.attributes), NUM_METATILES_IN_PRIMARY)
    table[:n] = primary.attributes[:n] & BEHAVIOR_MASK
    if secondary is not None:
        n = min(len(secondary.attributes), NUM_METATILES_IN_PRIMARY)
        table[NUM_METATILES_IN_PRIMARY:NUM_METATILES_IN_PRIMARY + n] = (
            secondary.attributes[:n] & BEHAVIOR_MASK
        )
    return table


def render_layout(blocks: np.ndarray, atlas: np.ndarray) -> Image.Image:
    """blocks (h, w) de metatile ids -> imagen RGBA de (h*16, w*16)."""
    height, width = blocks.shape
    canvas = (atlas[blocks]                     # (h, w, 16, 16, 4)
              .transpose(0, 2, 1, 3, 4)         # (h, 16, w, 16, 4)
              .reshape(height * 16, width * 16, 4))
    return Image.fromarray(canvas, mode="RGBA")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pokeemerald", help="ruta al clon de pret/pokeemerald")
    parser.add_argument("--only", help="renderizar solo este LAYOUT_ID")
    parser.add_argument("--no-mipmaps", action="store_true")
    args = parser.parse_args(argv)

    pe = resolve_pokeemerald(args.pokeemerald)
    layouts = load_json(DATA_DIR / "layouts.json")
    tileset_info = load_json(DATA_DIR / "tilesets.json")
    maps = load_json(DATA_DIR / "maps.json")["maps"]
    used_layouts = {m["layout"] for m in maps}
    behaviors = load_json(DATA_DIR / "metatile_behaviors.json")
    transition_ids = set(behaviors["transition_ids"])
    behavior_names = behaviors["names"]

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    tileset_cache: dict[str, Tileset] = {}
    atlas_cache: dict[tuple[str, str], np.ndarray] = {}
    behavior_cache: dict[tuple[str, str], np.ndarray] = {}

    def get_tileset(name: str) -> Tileset | None:
        if name not in tileset_info:
            return None
        if name not in tileset_cache:
            tileset_cache[name] = load_tileset(pe, name, tileset_info[name])
        return tileset_cache[name]

    warp_tiles: dict[str, dict[str, str]] = {}
    problems: list[str] = []
    rendered = 0
    started = time.monotonic()

    items = sorted(layouts.items())
    if args.only:
        items = [(k, v) for k, v in items if k == args.only]
        if not items:
            raise SystemExit(f"No existe el layout {args.only}")

    for layout_id, layout in items:
        primary = get_tileset(layout["primary_tileset"])
        if primary is None:
            problems.append(f"{layout_id}: sin tileset primario {layout['primary_tileset']}")
            continue
        secondary = get_tileset(layout["secondary_tileset"])

        key = (layout["primary_tileset"], layout["secondary_tileset"])
        if key not in atlas_cache:
            atlas_cache[key] = build_atlas(primary, secondary)
            behavior_cache[key] = build_behavior_table(primary, secondary)

        width, height = layout["width"], layout["height"]
        raw = np.fromfile(pe / layout["blockdata"], dtype="<u2")
        expected = width * height
        if raw.size < expected:
            problems.append(
                f"{layout_id}: blockdata incompleto, {raw.size} bloques para {width}x{height}"
            )
            continue
        if raw.size > expected:
            # Varios layouts sin usar comparten fichero o llevan relleno al
            # final; sobra informacion, no falta.
            if layout_id in used_layouts:
                problems.append(
                    f"{layout_id}: blockdata de {raw.size} bloques para {width}x{height}"
                )
            raw = raw[:expected]
        metatile_ids = (raw & METATILE_ID_MASK).reshape(height, width)

        image = render_layout(metatile_ids, atlas_cache[key])
        image.save(ASSETS_DIR / f"{layout_id}.png", optimize=True)
        if not args.no_mipmaps:
            for factor in MIPMAPS:
                small = image.resize(
                    (max(1, image.width // factor), max(1, image.height // factor)),
                    Image.Resampling.BOX,
                )
                small.save(ASSETS_DIR / f"{layout_id}.{factor}.png", optimize=True)

        # Casillas cuyo metatile es una puerta, escalera o agujero.
        tile_behaviors = behavior_cache[key][metatile_ids]
        marked: dict[str, str] = {}
        for y, x in zip(*np.nonzero(np.isin(tile_behaviors, list(transition_ids)))):
            marked[f"{x},{y}"] = behavior_names[int(tile_behaviors[y, x])]
        if marked:
            warp_tiles[layout_id] = marked

        rendered += 1
        if rendered % 50 == 0:
            print(f"  {rendered}/{len(items)}...", flush=True)

    if not args.only:
        write_json(DATA_DIR / "warp_tiles.json", warp_tiles, compact=True)

    elapsed = time.monotonic() - started
    print(f"renderizados: {rendered}/{len(items)} layouts en {elapsed:.1f}s")
    print(f"pares de tilesets distintos: {len(atlas_cache)}")
    print(f"layouts con casillas de transicion: {len(warp_tiles)}")

    if not args.only:
        # Lo que de verdad importa: que ningun mapa jugable se quede sin imagen.
        without_image = [
            m["id"] for m in maps
            if not (ASSETS_DIR / f"{m['layout']}.png").is_file()
        ]
        print(f"mapas sin imagen: {len(without_image)}")
        if without_image:
            problems.append(f"mapas sin imagen: {without_image[:10]}")
    if problems:
        print("\nIncidencias:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
