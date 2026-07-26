"""Compone el lienzo entero en un PNG reducido, para revisar el ensamblado.

No lo usa la aplicacion: sirve para ver de un vistazo si la geografia y la
banda de interiores han quedado bien.

Uso:
    python tools/preview_world.py [--scale 16] [--out preview.png]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import ASSETS_DIR, DATA_DIR, PROJECT_ROOT, load_json  # noqa: E402

BACKGROUND = (18, 20, 26)
OUTLINE = (70, 78, 92)
LABEL = (150, 160, 180)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", type=int, default=16, help="divisor de tamano")
    parser.add_argument("--out", default="preview.png")
    parser.add_argument("--outdoors-only", action="store_true")
    args = parser.parse_args()

    world = load_json(DATA_DIR / "world_layout.json")
    placements = world["placements"]
    scale = args.scale

    if args.outdoors_only:
        placements = {k: v for k, v in placements.items() if v["kind"] == "outdoor"}
        width = max(p["x"] + p["w"] for p in placements.values()) // scale
        height = max(p["y"] + p["h"] for p in placements.values()) // scale
    else:
        width, height = world["width"] // scale, world["height"] // scale

    canvas = Image.new("RGB", (max(1, width), max(1, height)), BACKGROUND)
    draw = ImageDraw.Draw(canvas)

    # Los mipmaps evitan cargar 441 imagenes a resolucion nativa.
    suffix = {4: ".4", 16: ".16"}.get(scale, "")
    missing = 0
    for map_id, placement in sorted(placements.items(), key=lambda kv: kv[1]["kind"]):
        path = ASSETS_DIR / f"{placement['layout']}{suffix}.png"
        if not path.is_file():
            path = ASSETS_DIR / f"{placement['layout']}.png"
        if not path.is_file():
            missing += 1
            continue
        image = Image.open(path).convert("RGBA")
        target = (max(1, placement["w"] // scale), max(1, placement["h"] // scale))
        if image.size != target:
            image = image.resize(target, Image.Resampling.BOX)
        canvas.paste(image, (placement["x"] // scale, placement["y"] // scale), image)

    if not args.outdoors_only:
        for section in world["sections"]:
            x, y = section["x"] // scale, section["y"] // scale
            draw.rectangle(
                [x, y, x + section["w"] // scale, y + section["h"] // scale],
                outline=OUTLINE,
            )
            draw.text((x + 2, y + 1), section["label"], fill=LABEL)

    out = PROJECT_ROOT / args.out
    canvas.save(out)
    print(f"{out}  ({canvas.width} x {canvas.height} px, faltaban {missing} imagenes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
