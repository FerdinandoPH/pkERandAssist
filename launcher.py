"""Arranque en un solo paso: prepara lo que falte y abre el asistente.

    python launcher.py

o, sin tocar la terminal, doble clic en `Iniciar.bat` (Windows) o en
`iniciar.sh` (Linux/macOS).

Hace por orden lo que hasta ahora habia que hacer a mano: crear el entorno
virtual, instalar las dependencias, generar los datos y las imagenes con
tools/setup.py y levantar el servidor, abriendo el navegador al final.
Se puede lanzar siempre: cada paso ya hecho se salta.

Solo usa la biblioteca estandar. Tiene que arrancar con el Python del sistema,
que es justamente el que todavia no tiene instalado nada.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# Al congelarlo con PyInstaller, __file__ apunta al descomprimido temporal: la
# raiz del proyecto es entonces la carpeta donde esta el ejecutable.
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent

VENV_DIR = PROJECT_ROOT / ".venv"
DATA_DIR = PROJECT_ROOT / "data" / "static"
ASSETS_DIR = PROJECT_ROOT / "assets" / "layouts"
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"

# Los mismos que app/datafiles.py da por imprescindibles.
REQUIRED_DATA = ("maps.json", "warps.json", "world_layout.json")
# El mismo umbral que tools/setup.py: menos es un render a medias.
MIN_ASSETS = 400

MIN_PYTHON = (3, 11)
DEFAULT_PORT = 8000
PORT_ATTEMPTS = 10
# Generar los atlas y arrancar FastAPI tarda; el margen es de sobra.
SERVER_TIMEOUT = 90.0


def say(message: str = "") -> None:
    print(message, flush=True)


def fail(message: str) -> SystemExit:
    """Aborta con un mensaje pensado para quien no programa."""
    return SystemExit(f"\n{message}")


# --- entorno ---------------------------------------------------------------

def venv_python() -> Path:
    """El interprete de dentro de .venv, exista o no todavia."""
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def host_python() -> str:
    """Interprete con el que crear el entorno virtual.

    Congelado no hay ninguno dentro, asi que hay que buscarlo en el PATH.
    """
    if not getattr(sys, "frozen", False):
        return sys.executable
    for candidate in ("py", "python3", "python"):
        found = shutil.which(candidate)
        if found and python_version_ok(found):
            return found
    raise fail(
        "No encuentro Python instalado.\n"
        "Descargalo de https://python.org (version 3.11 o superior) y, en\n"
        "Windows, marca la casilla 'Add Python to PATH' al instalarlo."
    )


def python_version_ok(executable: str) -> bool:
    """True si ese interprete cumple la version minima."""
    code = "import sys; print(sys.version_info.major, sys.version_info.minor)"
    try:
        out = subprocess.run([executable, "-c", code], capture_output=True,
                             text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    if out.returncode != 0:
        return False
    try:
        major, minor = (int(part) for part in out.stdout.split())
    except ValueError:
        return False
    return (major, minor) >= MIN_PYTHON


def ensure_venv() -> Path:
    """Devuelve el interprete de .venv, creandolo si hace falta."""
    python = venv_python()
    if python.is_file():
        return python

    say("Creando el entorno virtual (.venv)...")
    base = host_python()
    result = subprocess.run([base, "-m", "venv", str(VENV_DIR)])
    if result.returncode != 0 or not python.is_file():
        # En Debian/Ubuntu el modulo venv va en un paquete aparte.
        raise fail(
            "No he podido crear el entorno virtual.\n"
            "En Debian o Ubuntu suele faltar el paquete:\n"
            "  sudo apt install python3-venv"
        )
    return python


def deps_ready(python: Path) -> bool:
    """True si el entorno ya tiene todo lo que el asistente importa."""
    code = "import fastapi, uvicorn, numpy, PIL"
    result = subprocess.run([str(python), "-c", code], capture_output=True)
    return result.returncode == 0


def ensure_deps(python: Path) -> None:
    if deps_ready(python):
        return
    say("Instalando las dependencias (hace falta conexion, tarda un minuto)...")
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)])
    if result.returncode != 0 or not deps_ready(python):
        raise fail(
            "No he podido instalar las dependencias.\n"
            f"Pruebalo a mano:  {python} -m pip install -r {REQUIREMENTS}"
        )


# --- datos -----------------------------------------------------------------

def data_ready() -> bool:
    """True si estan los datos y las imagenes que genera tools/setup.py."""
    if not all((DATA_DIR / name).is_file() for name in REQUIRED_DATA):
        return False
    if not ASSETS_DIR.is_dir():
        return False
    return sum(1 for _ in ASSETS_DIR.glob("*.png")) >= MIN_ASSETS


def ensure_data(python: Path, force: bool = False) -> None:
    if data_ready() and not force:
        return
    say("Faltan los mapas. Los preparo ahora (una sola vez).")
    say("Si te pide la ruta de pokeemerald, pegala y pulsa Enter.\n")
    argv = [str(python), str(PROJECT_ROOT / "tools" / "setup.py")]
    if force:
        argv.append("--force")
    # Sin capturar: setup.py pregunta por la ruta y hay que poder contestar.
    result = subprocess.run(argv, cwd=PROJECT_ROOT)
    if result.returncode != 0 or not data_ready():
        raise fail(
            "La preparacion de los mapas no ha terminado bien.\n"
            "Mira el mensaje de arriba: casi siempre es que falta el clon de\n"
            "pokeemerald.  git clone --depth 1 "
            "https://github.com/pret/pokeemerald.git"
        )


# --- servidor --------------------------------------------------------------

def port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as probe:
        return probe.connect_ex((host, port)) != 0


def pick_port(preferred: int, host: str = "127.0.0.1") -> int:
    """El puerto pedido o el primero libre a continuacion."""
    for port in range(preferred, preferred + PORT_ATTEMPTS):
        if port_free(port, host):
            return port
    raise fail(
        f"Los puertos {preferred}-{preferred + PORT_ATTEMPTS - 1} estan ocupados.\n"
        "Cierra el asistente que ya tengas abierto o usa --port."
    )


def wait_until_up(process: subprocess.Popen, port: int, host: str) -> bool:
    """Espera a que el servidor acepte conexiones. False si murio antes."""
    deadline = time.time() + SERVER_TIMEOUT
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        if not port_free(port, host):
            return True
        time.sleep(0.25)
    return False


def serve(python: Path, host: str, port: int, open_browser: bool,
          trace: bool = False) -> int:
    """Levanta uvicorn y se queda esperando hasta que se cierre."""
    url = f"http://{host}:{port}"
    say(f"\nArrancando el asistente en {url} ...")
    environment = dict(os.environ)
    if trace:
        environment["PKER_TRACE"] = "1"
        say("Traza activada: se grabara en runs/trazas/ lo que mande el emulador.")
    # Sin --reload a proposito: el puente TCP se ata al 8765 y un recargado
    # deja el puerto ocupado.
    process = subprocess.Popen(
        [str(python), "-m", "uvicorn", "app.server:app",
         "--host", host, "--port", str(port)],
        cwd=PROJECT_ROOT, env=environment,
    )
    try:
        if not wait_until_up(process, port, host):
            process.terminate()
            raise fail("El servidor no ha llegado a arrancar. Mira el error de arriba.")

        say(f"Listo. Abre {url} en el navegador si no se abre solo.")
        say("En mGBA: Tools > Scripting... > File > Load script >"
            " bridge/pker_bridge.lua")
        say("\nPara cerrar el asistente, pulsa Ctrl+C en esta ventana.\n")
        if open_browser:
            webbrowser.open(url)

        return process.wait()
    except KeyboardInterrupt:
        say("\nCerrando...")
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"puerto del servidor (por defecto {DEFAULT_PORT})")
    parser.add_argument("--host", default="127.0.0.1",
                        help="interfaz donde escuchar")
    parser.add_argument("--no-browser", action="store_true",
                        help="no abrir el navegador al arrancar")
    parser.add_argument("--force-setup", action="store_true",
                        help="regenerar datos e imagenes aunque ya esten")
    parser.add_argument("--setup-only", action="store_true",
                        help="preparar todo pero no arrancar el servidor")
    parser.add_argument("--trace", action="store_true",
                        help="grabar en runs/trazas/ lo que manda el emulador, "
                             "para investigar una puerta que no se registra")
    args = parser.parse_args(argv)

    say("Asistente de mapa para Esmeralda Warp Randomizer")
    say(f"Carpeta: {PROJECT_ROOT}\n")

    if not REQUIREMENTS.is_file():
        raise fail(
            f"No encuentro requirements.txt en {PROJECT_ROOT}.\n"
            "El lanzador tiene que estar dentro de la carpeta del proyecto."
        )

    python = ensure_venv()
    ensure_deps(python)
    ensure_data(python, force=args.force_setup)

    if args.setup_only:
        say("\nTodo preparado.")
        return 0

    return serve(python, args.host, pick_port(args.port, args.host),
                 not args.no_browser, trace=args.trace)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as error:
        # Doble clic en Windows: sin esto la ventana se cierra y no da tiempo
        # a leer por que ha fallado.
        if error.code not in (0, None) and os.name == "nt" and sys.stdin.isatty():
            print(error, file=sys.stderr, flush=True)
            input("\nPulsa Enter para cerrar.")
            raise SystemExit(1) from None
        raise
