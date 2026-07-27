"""Tests del lanzador de un solo paso.

Nada de esto arranca servidores ni instala paquetes: se comprueban las
decisiones que toma el lanzador (que falta, que puerto, cuando se salta un
paso), que es donde puede equivocarse.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import launcher  # noqa: E402


@pytest.fixture
def fake_project(tmp_path, monkeypatch):
    """Un proyecto vacio y sin preparar en un directorio temporal."""
    monkeypatch.setattr(launcher, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(launcher, "DATA_DIR", tmp_path / "data" / "static")
    monkeypatch.setattr(launcher, "ASSETS_DIR", tmp_path / "assets" / "layouts")
    monkeypatch.setattr(launcher, "VENV_DIR", tmp_path / ".venv")
    return tmp_path


def prepare_data(root: Path, *, assets: int = launcher.MIN_ASSETS) -> None:
    """Deja el proyecto falso como si tools/setup.py ya hubiera corrido."""
    data = root / "data" / "static"
    data.mkdir(parents=True, exist_ok=True)
    for name in launcher.REQUIRED_DATA:
        (data / name).write_text("{}", encoding="utf-8")
    layouts = root / "assets" / "layouts"
    layouts.mkdir(parents=True, exist_ok=True)
    for index in range(assets):
        (layouts / f"{index}.png").write_bytes(b"")


# ---- que falta por preparar --------------------------------------------

def test_proyecto_vacio_no_esta_preparado(fake_project):
    assert not launcher.data_ready()


def test_proyecto_completo_esta_preparado(fake_project):
    prepare_data(fake_project)
    assert launcher.data_ready()


def test_un_render_a_medias_no_cuenta_como_preparado(fake_project):
    """Interrumpir render_maps.py deja imagenes sueltas: hay que rehacerlo."""
    prepare_data(fake_project, assets=launcher.MIN_ASSETS - 1)
    assert not launcher.data_ready()


def test_faltar_un_json_no_cuenta_como_preparado(fake_project):
    prepare_data(fake_project)
    (fake_project / "data" / "static" / "world_layout.json").unlink()
    assert not launcher.data_ready()


def test_con_los_datos_hechos_no_se_relanza_setup(fake_project, monkeypatch):
    prepare_data(fake_project)
    monkeypatch.setattr(launcher.subprocess, "run", _explode)
    launcher.ensure_data(Path("python"))  # no debe llamar a subprocess


def test_con_force_se_relanza_setup_aunque_este_hecho(fake_project, monkeypatch):
    prepare_data(fake_project)
    llamadas = []

    def fake_run(argv, **kwargs):
        llamadas.append(argv)
        return _Result(0)

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    launcher.ensure_data(Path("python"), force=True)
    assert len(llamadas) == 1
    assert "--force" in llamadas[0]


def test_setup_que_falla_aborta_con_mensaje(fake_project, monkeypatch):
    monkeypatch.setattr(launcher.subprocess, "run",
                        lambda argv, **kwargs: _Result(1))
    with pytest.raises(SystemExit) as error:
        launcher.ensure_data(Path("python"))
    assert "pokeemerald" in str(error.value)


def test_setup_que_dice_ir_bien_sin_dejar_datos_tambien_aborta(
        fake_project, monkeypatch):
    """Devolver 0 no basta: lo que vale es que los datos esten."""
    monkeypatch.setattr(launcher.subprocess, "run",
                        lambda argv, **kwargs: _Result(0))
    with pytest.raises(SystemExit):
        launcher.ensure_data(Path("python"))


# ---- entorno virtual ----------------------------------------------------

def test_con_venv_ya_creado_no_se_vuelve_a_crear(fake_project, monkeypatch):
    python = launcher.venv_python()
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    monkeypatch.setattr(launcher.subprocess, "run", _explode)
    assert launcher.ensure_venv() == python


def test_venv_que_no_aparece_aborta_con_la_pista_de_apt(
        fake_project, monkeypatch):
    """python3-venv no viene de serie en Debian, y ahi es donde falla."""
    monkeypatch.setattr(launcher.subprocess, "run",
                        lambda argv, **kwargs: _Result(0))
    with pytest.raises(SystemExit) as error:
        launcher.ensure_venv()
    assert "python3-venv" in str(error.value)


# ---- puertos ------------------------------------------------------------

def test_se_prefiere_el_puerto_pedido():
    with socket.socket() as libre:
        libre.bind(("127.0.0.1", 0))
        port = libre.getsockname()[1]
    assert launcher.pick_port(port) == port


def test_un_puerto_ocupado_pasa_al_siguiente():
    """Tener ya un asistente abierto no debe impedir abrir otro."""
    with socket.socket() as ocupado:
        ocupado.bind(("127.0.0.1", 0))
        ocupado.listen(1)
        port = ocupado.getsockname()[1]
        assert launcher.pick_port(port) != port


def test_sin_ningun_puerto_libre_se_avisa(monkeypatch):
    monkeypatch.setattr(launcher, "port_free", lambda port, host="127.0.0.1": False)
    with pytest.raises(SystemExit) as error:
        launcher.pick_port(8000)
    assert "--port" in str(error.value)


# ---- ayudas -------------------------------------------------------------

class _Result:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def _explode(*args, **kwargs):
    raise AssertionError("no deberia lanzarse ningun proceso")
