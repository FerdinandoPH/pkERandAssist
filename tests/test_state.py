"""Tests de la gestion de partidas.

No necesitan ni emulador ni los datos generados: todo lo de aqui es logica
de ficheros y de normalizacion.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import state as state_module  # noqa: E402
from app.state import (  # noqa: E402
    Run, list_runs, run_path, safe_run_name, validate_payload,
)


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    """Redirige runs/ a un directorio temporal."""
    monkeypatch.setattr(state_module, "RUNS_DIR", tmp_path)
    return tmp_path


# ---- nombres de partida ------------------------------------------------

@pytest.mark.parametrize("entrada, esperado", [
    ("partida 1", "partida 1"),
    ("  espacios  ", "espacios"),
    ("dobles   espacios", "dobles espacios"),
    ("acentuada-ñ", "acentuada-"),      # se filtran los no ASCII
    ("../../etc/passwd", "....etcpasswd"),
    ("a/b\\c", "abc"),
    ("nombre.", "nombre"),              # Windows se comeria el punto final
])
def test_safe_run_name_normaliza(entrada, esperado):
    assert safe_run_name(entrada) == esperado


@pytest.mark.parametrize("entrada", ["", "   ", ".", "..", "///", "CON", "com1", "LPT9"])
def test_safe_run_name_rechaza(entrada):
    with pytest.raises(ValueError):
        safe_run_name(entrada)


def test_safe_run_name_recorta_largo():
    assert len(safe_run_name("x" * 200)) == 40


def test_run_path_no_escapa_del_directorio(runs_dir):
    """Lo que de verdad importa: nada puede escribir fuera de runs/."""
    for intento in ("../fuera", "../../etc/passwd", "sub/dir"):
        assert run_path(intento).resolve().parent == runs_dir.resolve()


# ---- listado -----------------------------------------------------------

def test_list_runs_vacio_si_no_hay_directorio(runs_dir, monkeypatch):
    monkeypatch.setattr(state_module, "RUNS_DIR", runs_dir / "no-existe")
    assert list_runs() == []


def test_list_runs_cuenta_progreso(runs_dir):
    run = Run(name="una")
    run.visit("MAP_A")
    run.visit("MAP_B")
    run.add_link("MAP_A", 0, "MAP_B", 1)
    run.add_link("MAP_B", 1, "MAP_A", 0)   # confirma el par en los dos sentidos

    entries = {e["name"]: e for e in list_runs()}
    assert entries["una"]["maps"] == 2
    assert entries["una"]["links"] == 2
    assert entries["una"]["confirmed"] == 2
    assert entries["una"]["error"] is False


def test_list_runs_sobrevive_a_un_fichero_corrupto(runs_dir):
    Run(name="buena").visit("MAP_A")
    (runs_dir / "rota.json").write_text("{esto no es json", encoding="utf-8")

    entries = {e["name"]: e for e in list_runs()}
    assert entries["buena"]["error"] is False
    assert entries["rota"]["error"] is True


# ---- cambio de partida -------------------------------------------------

def test_switch_to_conserva_el_objeto(runs_dir):
    """La garantia de la que depende todo: el tracker guarda una referencia a
    este Run, asi que cambiar de partida no puede cambiar el objeto."""
    otra = Run(name="otra")
    otra.visit("MAP_OTRA")

    run = Run.load("default")
    run.visit("MAP_DEFAULT")
    identidad = id(run)

    run.switch_to("otra")
    assert id(run) == identidad
    assert run.name == "otra"
    assert "MAP_OTRA" in run.visited
    assert "MAP_DEFAULT" not in run.visited

    run.switch_to("default")
    assert id(run) == identidad
    assert "MAP_DEFAULT" in run.visited


def test_switch_to_partida_nueva_arranca_vacia(runs_dir):
    run = Run.load("default")
    run.visit("MAP_A")
    run.switch_to("recien-creada")
    assert run.visited == {}
    assert run.links == {}


def test_switch_to_escribe_en_la_partida_nueva(runs_dir):
    run = Run.load("default")
    run.switch_to("segunda")
    run.visit("MAP_NUEVO")

    with open(runs_dir / "segunda.json", encoding="utf-8") as fh:
        assert "MAP_NUEVO" in json.load(fh)["visited"]
    assert not (runs_dir / "default.json").is_file()


# ---- importacion -------------------------------------------------------

def test_validate_payload_acepta_visited_como_diccionario():
    content, warnings = validate_payload({
        "visited": {"MAP_A": 123.0},
        "links": {"MAP_A:0": {"from_map": "MAP_A", "from_warp": 0,
                              "to_map": "MAP_B", "to_warp": 1}},
    })
    assert content["visited"] == {"MAP_A": 123.0}
    assert content["links"]["MAP_A:0"]["to_map"] == "MAP_B"
    assert content["links"]["MAP_A:0"]["return_seen"] is False
    assert warnings == []


def test_validate_payload_acepta_visited_como_lista():
    """Es lo que devuelve snapshot(), y es lo que el usuario puede pegar."""
    content, _ = validate_payload({"visited": ["MAP_A", "MAP_B"], "links": []})
    assert set(content["visited"]) == {"MAP_A", "MAP_B"}


def test_validate_payload_descarta_basura_sin_perder_lo_bueno():
    content, warnings = validate_payload({
        "visited": ["MAP_A"],
        "links": [
            {"from_map": "MAP_A", "from_warp": 0, "to_map": "MAP_B", "to_warp": 1},
            {"from_map": "MAP_C"},          # incompleto
            "esto no es un enlace",
        ],
    })
    assert len(content["links"]) == 1
    assert "2 puertas descartadas" in warnings[0]


@pytest.mark.parametrize("entrada", [None, [], "texto", 42, {"otra_cosa": 1}])
def test_validate_payload_rechaza_lo_que_no_es_una_partida(entrada):
    with pytest.raises(ValueError):
        validate_payload(entrada)


def test_replace_with_sustituye_y_guarda(runs_dir):
    run = Run.load("destino")
    run.visit("MAP_VIEJO")
    content, _ = validate_payload({"visited": ["MAP_NUEVO"], "links": []})
    run.replace_with(content)

    assert "MAP_VIEJO" not in run.visited
    with open(runs_dir / "destino.json", encoding="utf-8") as fh:
        assert list(json.load(fh)["visited"]) == ["MAP_NUEVO"]
