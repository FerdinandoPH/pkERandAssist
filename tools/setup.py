"""Preparacion guiada: deja el proyecto listo para usar en un solo comando.

    python tools/setup.py

Pregunta donde esta el clon de pret/pokeemerald y encadena los tres pasos de
generacion. Se puede repetir sin miedo: salta lo que ya este hecho salvo que
se pase --force.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    ASSETS_DIR, DATA_DIR, DEFAULT_POKEEMERALD, PROJECT_ROOT, resolve_pokeemerald,
)

# Menos de esto es un render a medias, no un render hecho.
MIN_ASSETS = 400


def check_environment() -> list[str]:
    """Avisos sobre el interprete y las dependencias. No aborta."""
    warnings = []
    if sys.version_info < (3, 11):
        warnings.append(
            f"Python {sys.version_info.major}.{sys.version_info.minor}: "
            "el proyecto usa sintaxis de 3.11+"
        )
    for module, package in (("PIL", "pillow"), ("numpy", "numpy"), ("fastapi", "fastapi")):
        try:
            __import__(module)
        except ImportError:
            warnings.append(f"falta {package}  (pip install -r requirements.txt)")
    return warnings


def done_steps() -> dict[str, bool]:
    """Que pasos estan ya hechos, para no repetirlos."""
    assets = list(ASSETS_DIR.glob("*.png")) if ASSETS_DIR.is_dir() else []
    return {
        "datos": (DATA_DIR / "maps.json").is_file() and (DATA_DIR / "warps.json").is_file(),
        "imagenes": len(assets) >= MIN_ASSETS,
        "layout": (DATA_DIR / "world_layout.json").is_file(),
    }


def ask_pokeemerald(preset: str | None, assume_yes: bool) -> Path:
    """Devuelve una ruta valida a pokeemerald, preguntando si hace falta."""
    if preset or assume_yes:
        return resolve_pokeemerald(preset)

    # Si la ruta por defecto ya sirve, no marear con preguntas.
    try:
        return resolve_pokeemerald(None)
    except SystemExit:
        pass

    print(f"No encuentro pokeemerald en {DEFAULT_POKEEMERALD}.")
    print("Si no lo tienes, clonalo con:")
    print("  git clone --depth 1 https://github.com/pret/pokeemerald.git\n")
    while True:
        answer = input("Ruta al clon de pokeemerald (vacio para salir): ").strip()
        # Al arrastrar una carpeta a la consola llegan comillas y ~ sin expandir.
        answer = answer.strip('"').strip("'")
        if not answer:
            raise SystemExit("Cancelado.")
        try:
            return resolve_pokeemerald(str(Path(answer).expanduser()))
        except SystemExit as error:
            print(f"\n{error}\n")


def run_step(title: str, function, argv: list[str]) -> bool:
    """Ejecuta un paso mostrando titulo y tiempo. True si fue bien."""
    print(f"\n=== {title} ===", flush=True)
    started = time.time()
    try:
        code = function(argv)
    except SystemExit as error:  # los scripts abortan asi cuando algo falta
        print(str(error), file=sys.stderr)
        return False
    elapsed = time.time() - started
    if code != 0:
        print(f"-> fallo tras {elapsed:.1f}s", file=sys.stderr)
        return False
    print(f"-> hecho en {elapsed:.1f}s", flush=True)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pokeemerald", help="ruta al clon de pret/pokeemerald")
    parser.add_argument("--yes", action="store_true",
                        help="no preguntar nada (para automatizar)")
    parser.add_argument("--force", action="store_true",
                        help="rehacer tambien los pasos ya completados")
    args = parser.parse_args(argv)

    print("Preparacion de pkERandAssist")
    print(f"Proyecto: {PROJECT_ROOT}")

    for warning in check_environment():
        print(f"  aviso: {warning}")

    # Comprobar que falta ANTES de pedir la ruta: si no hay nada que hacer,
    # no tiene sentido exigir el clon de pokeemerald.
    done = done_steps()
    if not args.force and all(done.values()):
        print("\nTodo estaba hecho ya. Usa --force para rehacerlo.")
        print_next_steps()
        return 0

    pokeemerald = ask_pokeemerald(args.pokeemerald, args.yes)
    print(f"pokeemerald: {pokeemerald}")

    # Import aqui y no arriba: sin pillow/numpy, importarlos revienta antes de
    # poder dar el aviso de que faltan.
    import build_data
    import build_layout
    import render_maps

    ruta = ["--pokeemerald", str(pokeemerald)]
    steps = [
        ("datos", "Extrayendo datos de pokeemerald", build_data.main, ruta),
        ("imagenes", "Renderizando los mapas (tarda un poco)", render_maps.main, ruta),
        ("layout", "Ensamblando el mundo", build_layout.main, []),
    ]

    for key, title, function, step_argv in steps:
        if done[key] and not args.force:
            print(f"\n=== {title} ===\n-> ya estaba hecho, se salta")
            continue
        if not run_step(title, function, step_argv):
            print("\nLa preparacion se ha detenido. Corrige lo de arriba y "
                  "vuelve a lanzar el comando.", file=sys.stderr)
            return 1

    print_next_steps()
    return 0


def print_next_steps() -> None:
    print("\nListo. Ahora:")
    print("  uvicorn app.server:app        y abre http://127.0.0.1:8000")
    print("  en mGBA, Tools > Scripting > carga bridge/pker_bridge.lua")


if __name__ == "__main__":
    raise SystemExit(main())
