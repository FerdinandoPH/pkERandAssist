"""Tests del tracker con trazas grabadas.

Las muestras se reproducen sin emulador, asi que toda la logica de deteccion
se prueba en frio. Los datos son los reales de data/static, de modo que estos
tests tambien validan que la extraccion sigue siendo coherente.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import state as state_module  # noqa: E402
from app.state import Run  # noqa: E402
from app.tracker import Sample, Tracker  # noqa: E402

DATA_DIR = PROJECT_ROOT / "data" / "static"

BRENDANS_1F = "MAP_LITTLEROOT_TOWN_BRENDANS_HOUSE_1F"
BRENDANS_2F = "MAP_LITTLEROOT_TOWN_BRENDANS_HOUSE_2F"
MOSSDEEP_GYM = "MAP_MOSSDEEP_CITY_GYM"
LITTLEROOT = "MAP_LITTLEROOT_TOWN"
ROUTE101 = "MAP_ROUTE101"
SKY_PILLAR_TOP = "MAP_SKY_PILLAR_TOP"
SKY_PILLAR_5F = "MAP_SKY_PILLAR_5F"
# El caso que se vio fallando en una partida real: la escalera de la Torre
# Fantasma (warp 1, en 15,2) llevaba a la Cueva Granito B2F.
MIRAGE_1F = "MAP_MIRAGE_TOWER_1F"
GRANITE_B2F = "MAP_GRANITE_CAVE_B2F"


def read(name: str):
    path = DATA_DIR / name
    if not path.is_file():
        pytest.skip(f"faltan los datos generados ({name}); "
                    "ejecuta tools/build_data.py y tools/render_maps.py")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def static_data():
    return {
        "maps": read("maps.json")["maps"],
        "warps": read("warps.json"),
        "warp_tiles": read("warp_tiles.json"),
    }


@pytest.fixture
def make_tracker(static_data, tmp_path, monkeypatch):
    """Un tracker limpio con su partida, guardando en un directorio temporal."""
    monkeypatch.setattr(state_module, "RUNS_DIR", tmp_path)
    run = Run(name="test")
    tracker = Tracker(
        maps=static_data["maps"],
        warps=static_data["warps"],
        warp_tiles=static_data["warp_tiles"],
        run=run,
    )
    return tracker, run


@pytest.fixture
def indices(static_data):
    return {m["id"]: (m["map_group"], m["map_num"]) for m in static_data["maps"]}


@pytest.fixture
def at(indices):
    """Construye una muestra como la que mandaria el emulador."""
    def build(map_id: str, x: int, y: int, warp: int = -1, frame: int = 0) -> Sample:
        group, num = indices[map_id]
        return Sample(group, num, warp, x, y, frame)
    return build


def links_of(events):
    return [e["link"] for e in events if e["type"] == "link"]


def specials_of(events):
    return [e["special"] for e in events if e["type"] == "special"]


def test_puerta_normal(make_tracker, at):
    """Salir por una puerta registra el par origen -> destino."""
    tracker, _ = make_tracker
    events = tracker.replay([
        at(BRENDANS_1F, 9, 6, warp=2),
        at(BRENDANS_1F, 9, 7, warp=2),
        at(BRENDANS_1F, 9, 8, warp=2),      # pisa la puerta (warp 0)
        at(MOSSDEEP_GYM, 7, 35, warp=1),    # aparece en el gimnasio
    ])

    links = links_of(events)
    assert len(links) == 1
    assert (links[0]["from_map"], links[0]["from_warp"]) == (BRENDANS_1F, 0)
    assert (links[0]["to_map"], links[0]["to_warp"]) == (MOSSDEEP_GYM, 1)
    assert links[0]["return_seen"] is False


def test_par_confirmado_al_volver(make_tracker, at):
    """Recorrer el sentido contrario marca el par como bidireccional."""
    tracker, run = make_tracker
    tracker.replay([
        at(BRENDANS_1F, 9, 7, warp=2),
        at(BRENDANS_1F, 9, 8, warp=2),
        at(MOSSDEEP_GYM, 7, 35, warp=1),
    ])
    events = tracker.replay([
        at(MOSSDEEP_GYM, 7, 34, warp=1),
        at(MOSSDEEP_GYM, 7, 35, warp=1),    # pisa la misma puerta de vuelta
        at(BRENDANS_1F, 9, 8, warp=0),
    ])

    links = links_of(events)
    assert len(links) == 1
    assert links[0]["return_seen"] is True
    # El sentido original tambien queda marcado.
    assert run.links[f"{BRENDANS_1F}:0"]["return_seen"] is True


def test_escalera_dentro_de_la_casa(make_tracker, at):
    """Las escaleras son warps normales y se emparejan igual."""
    tracker, _ = make_tracker
    events = tracker.replay([
        at(BRENDANS_1F, 8, 3, warp=0),
        at(BRENDANS_1F, 8, 2, warp=0),      # warp 2 de la casa
        at(BRENDANS_2F, 8, 2, warp=0),
    ])

    links = links_of(events)
    assert len(links) == 1
    assert (links[0]["from_map"], links[0]["from_warp"]) == (BRENDANS_1F, 2)
    assert links[0]["to_map"] == BRENDANS_2F


def test_teletransporte_dentro_del_mismo_mapa(make_tracker, at):
    """El gimnasio de Algaria teletransporta sin cambiar de mapa.

    Es el caso que un detector basado solo en 'ha cambiado el mapa' se pierde.
    """
    tracker, _ = make_tracker
    events = tracker.replay([
        at(MOSSDEEP_GYM, 3, 29, warp=1),
        at(MOSSDEEP_GYM, 3, 28, warp=1),    # warp 2
        at(MOSSDEEP_GYM, 1, 23, warp=3),    # sale por el warp 3, mismo mapa
    ])

    links = links_of(events)
    assert len(links) == 1
    assert (links[0]["from_map"], links[0]["from_warp"]) == (MOSSDEEP_GYM, 2)
    assert (links[0]["to_map"], links[0]["to_warp"]) == (MOSSDEEP_GYM, 3)


def test_conexion_entre_rutas_no_es_una_puerta(make_tracker, at):
    """Caminar de un mapa a otro contiguo revela zona, pero no es un warp."""
    tracker, _ = make_tracker
    events = tracker.replay([
        at(LITTLEROOT, 10, 1, warp=1),
        at(LITTLEROOT, 10, 0, warp=1),
        at(ROUTE101, 10, 39, warp=-1),
    ])

    assert links_of(events) == []
    specials = specials_of(events)
    assert len(specials) == 1
    assert specials[0]["kind"] == "connection"
    assert specials[0]["to_map"] == ROUTE101


def test_agujero_en_el_suelo(make_tracker, at, static_data):
    """Caer por un suelo agrietado no sale de warp_events: se usa el metatile."""
    tracker, _ = make_tracker
    maps = {m["id"]: m for m in static_data["maps"]}
    tiles = static_data["warp_tiles"][maps[SKY_PILLAR_TOP]["layout"]]
    hole = next(key for key, behavior in tiles.items()
                if behavior == "MB_CRACKED_FLOOR_HOLE")
    hx, hy = (int(v) for v in hole.split(","))

    events = tracker.replay([
        at(SKY_PILLAR_TOP, hx, hy - 1, warp=0),
        at(SKY_PILLAR_TOP, hx, hy, warp=0),      # pisa el agujero
        at(SKY_PILLAR_5F, hx, hy, warp=-1),      # cae al piso de abajo
    ])

    assert links_of(events) == []
    specials = specials_of(events)
    assert len(specials) == 1
    assert specials[0]["kind"] == "tile"
    assert specials[0]["detail"]["behavior"] == "MB_CRACKED_FLOOR_HOLE"


def test_caminar_no_genera_transiciones(make_tracker, at):
    """Moverse por el mapa no debe inventarse puertas."""
    tracker, _ = make_tracker
    events = tracker.replay([
        at(BRENDANS_1F, 4, 5, warp=0),
        at(BRENDANS_1F, 5, 5, warp=0),
        at(BRENDANS_1F, 6, 5, warp=0),
        at(BRENDANS_1F, 6, 6, warp=0),
    ])

    assert links_of(events) == []
    assert specials_of(events) == []


def test_un_hueco_en_el_muestreo_no_inventa_una_puerta(make_tracker, at):
    """Un salto de posicion sobre una casilla con puerta no es un warp.

    Si se pierden muestras (savestate, emulador atascado), el jugador puede
    'aparecer' lejos dentro del mismo mapa. Eso no puede registrarse como una
    puerta que lleva a si misma.
    """
    tracker, run = make_tracker
    events = tracker.replay([
        at(LITTLEROOT, 5, 9, warp=1),     # justo al lado del warp 1, en (5,8)
        at(LITTLEROOT, 6, 30, warp=1),    # salto imposible, mismo mapa y warp
    ])

    assert links_of(events) == []
    assert run.links == {}


def test_la_posicion_de_destino_llega_antes_que_el_cambio_de_mapa(make_tracker, at):
    """Durante el fundido el bloque de guardado se adelanta, y no es un warp.

    Cruzando una puerta hay muestras en las que la posicion ya es la del otro
    lado pero el mapa sigue siendo el de origen. Tomar ese salto por una
    puerta registraba un enlace del mapa consigo mismo que ademas se quedaba
    en el sitio del bueno: la escalera no aparecia unida a nada.
    """
    tracker, run = make_tracker
    events = tracker.replay([
        at(MIRAGE_1F, 15, 4, warp=0),
        at(MIRAGE_1F, 15, 3, warp=0),
        at(MIRAGE_1F, 15, 2, warp=0),        # pisa la escalera (warp 1)
        at(MIRAGE_1F, 29, 13, warp=0),       # posicion del destino, mapa viejo
        at(GRANITE_B2F, 29, 13, warp=0),
    ])

    links = links_of(events)
    assert len(links) == 1
    assert (links[0]["from_map"], links[0]["from_warp"]) == (MIRAGE_1F, 1)
    assert (links[0]["to_map"], links[0]["to_warp"]) == (GRANITE_B2F, 0)
    assert list(run.links) == [f"{MIRAGE_1F}:1"]


def test_un_fundido_largo_no_echa_la_puerta_del_historial(make_tracker, at):
    """El fundido dura mucho mas que el muestreo: llegan muestras repetidas.

    Con el historial contando muestras sueltas en vez de posiciones, esas
    repeticiones expulsaban la casilla de la escalera y la transicion se
    quedaba sin puerta de origen.
    """
    tracker, _ = make_tracker
    samples = [at(MIRAGE_1F, 15, 3, warp=0), at(MIRAGE_1F, 15, 2, warp=0)]
    samples += [at(MIRAGE_1F, 29, 13, warp=0)] * 30
    samples.append(at(GRANITE_B2F, 29, 13, warp=0))

    links = links_of(tracker.replay(samples))
    assert len(links) == 1
    assert (links[0]["from_map"], links[0]["from_warp"]) == (MIRAGE_1F, 1)
    assert links[0]["to_map"] == GRANITE_B2F


def test_esperar_quieto_sobre_una_puerta_no_la_pierde(make_tracker, at):
    """La misma casilla repetida ocupa un solo hueco del historial."""
    tracker, _ = make_tracker
    samples = [at(MIRAGE_1F, 15, 3, warp=0)]
    samples += [at(MIRAGE_1F, 15, 2, warp=0)] * 40
    samples.append(at(GRANITE_B2F, 29, 13, warp=0))

    links = links_of(tracker.replay(samples))
    assert len(links) == 1
    assert (links[0]["from_map"], links[0]["from_warp"]) == (MIRAGE_1F, 1)


def test_un_salto_sin_cambiar_de_warp_no_registra_nada(make_tracker, at):
    """Aparecer lejos con el mismo warp_id no es haber cruzado una puerta."""
    tracker, run = make_tracker
    events = tracker.replay([
        at(MIRAGE_1F, 15, 2, warp=0),     # sobre la escalera
        at(MIRAGE_1F, 3, 3, warp=0),      # salto imposible, mismo warp_id
    ])

    assert links_of(events) == []
    assert specials_of(events) == []
    assert run.links == {}


def test_destino_sin_warp_id_se_deduce_por_la_casilla(make_tracker, at):
    """Un destino dinamico deja warp_id en -1; queda la posicion de llegada."""
    tracker, _ = make_tracker
    events = tracker.replay([
        at(MIRAGE_1F, 15, 3, warp=0),
        at(MIRAGE_1F, 15, 2, warp=0),
        at(GRANITE_B2F, 29, 13, warp=-1),   # cae justo en la puerta 0
    ])

    links = links_of(events)
    assert len(links) == 1
    assert (links[0]["to_map"], links[0]["to_warp"]) == (GRANITE_B2F, 0)


def test_mapas_visitados_y_persistencia(make_tracker, at):
    """El progreso se guarda y se recupera tal cual."""
    tracker, run = make_tracker
    tracker.replay([
        at(BRENDANS_1F, 9, 8, warp=2),
        at(MOSSDEEP_GYM, 7, 35, warp=1),
    ])

    assert set(run.visited) == {BRENDANS_1F, MOSSDEEP_GYM}
    recovered = Run.load("test")
    assert set(recovered.visited) == {BRENDANS_1F, MOSSDEEP_GYM}
    assert recovered.links[f"{BRENDANS_1F}:0"]["to_map"] == MOSSDEEP_GYM


def test_indice_de_mapa_desconocido_se_ignora(make_tracker):
    """Lecturas de RAM sin sentido (menu, carga) no deben romper nada."""
    tracker, run = make_tracker
    assert tracker.replay([Sample(99, 99, -1, 0, 0)]) == []
    assert run.visited == {}


def test_cambiar_de_partida_no_inventa_una_transicion(make_tracker, at):
    """Al cambiar de partida hay que olvidar por donde ibas.

    Si no, la ultima lectura de la partida anterior se compara con la primera
    de la nueva y se registra una puerta entre dos sitios por los que nunca se
    ha pasado seguidos.
    """
    tracker, run = make_tracker
    tracker.replay([
        at(BRENDANS_1F, 9, 7, warp=2),
        at(BRENDANS_1F, 9, 8, warp=2),    # pisando la puerta
    ])

    tracker.forget_history()
    run.switch_to("otra")

    events = tracker.replay([at(MOSSDEEP_GYM, 7, 35, warp=1)])
    assert links_of(events) == []
    assert specials_of(events) == []
    assert run.links == {}


def test_ultima_posicion_conocida(make_tracker, at):
    """Recargar la pagina no debe perder donde estabas."""
    tracker, _ = make_tracker
    assert tracker.last_player() is None

    tracker.replay([at(LITTLEROOT, 5, 9, warp=1)])
    assert tracker.last_player() == {
        "type": "player", "map": LITTLEROOT, "x": 5, "y": 9, "warp": 1,
    }

    tracker.forget_history()
    assert tracker.last_player() is None
