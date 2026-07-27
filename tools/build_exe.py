"""Empaqueta el lanzador en un ejecutable suelto (opcional).

    python tools/build_exe.py

Sale `dist/pkERandAssist.exe` en Windows y `dist/pkERandAssist` en Linux o
macOS. Hay que **copiarlo a la carpeta del proyecto**: el ejecutable solo lleva
dentro el lanzador, y busca el resto (requirements.txt, app/, tools/) al lado
de si mismo.

Ojo con lo que el ejecutable NO evita, porque no puede: sigue haciendo falta
Python instalado en el sistema (el asistente corre en su propio .venv, que hay
que crear con un Python de verdad) y el clon de pokeemerald. Para casi todo el
mundo, `Iniciar.bat` o `iniciar.sh` cumplen lo mismo sin compilar nada.

PyInstaller no viene en requirements.txt porque solo hace falta aqui:
    pip install pyinstaller
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import PROJECT_ROOT  # noqa: E402

NAME = "pkERandAssist"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=NAME, help="nombre del ejecutable")
    args = parser.parse_args(argv)

    if shutil.which("pyinstaller") is None:
        print("Falta PyInstaller.  pip install pyinstaller", file=sys.stderr)
        return 1

    launcher = PROJECT_ROOT / "launcher.py"
    if not launcher.is_file():
        print(f"No encuentro {launcher}", file=sys.stderr)
        return 1

    # --onefile: un solo archivo que copiar. --console: el asistente escribe
    # por la terminal y se cierra con Ctrl+C, sin ventana no habria ni una cosa
    # ni la otra.
    result = subprocess.run(
        ["pyinstaller", "--onefile", "--console", "--name", args.name,
         "--distpath", str(PROJECT_ROOT / "dist"),
         "--workpath", str(PROJECT_ROOT / "build"),
         "--specpath", str(PROJECT_ROOT / "build"),
         str(launcher)],
        cwd=PROJECT_ROOT,
    )
    if result.returncode != 0:
        return result.returncode

    binary = PROJECT_ROOT / "dist" / (
        f"{args.name}.exe" if sys.platform == "win32" else args.name)
    print(f"\nHecho: {binary}")
    print(f"Copialo a {PROJECT_ROOT} y ejecutalo desde ahi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
