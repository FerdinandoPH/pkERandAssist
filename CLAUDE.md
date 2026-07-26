# Contexto del proyecto

Asistente de mapa para Pokémon Esmeralda parcheada con el
[Universal Warp Randomizer](https://warprandomizer.com/) (ROM USA). Lee el
estado del juego desde mGBA, revela los mapas que el jugador pisa sobre un
lienzo con los gráficos reales y empareja las puertas que va cruzando.

El usuario escribe en castellano; los comentarios de código, la documentación
y los mensajes al usuario van en castellano (sin tildes en el código, para
evitar problemas de codificación en consola Windows). Los identificadores del
código, en inglés.

Documentación: `docs/MANUAL.md` (uso) y `docs/COMO_FUNCIONA.md` (divulgativa).

---

## Reglas que no se deben romper

**1. Los destinos vanilla no se usan jamás.**
`data/static/warps_vanilla.json` contiene a dónde llevaba cada puerta en el
juego sin parchear. Está extraído solo para depurar. Usarlo en el tracker o en
la interfaz destriparía la partida, que es justo lo que el proyecto evita. Lo
único que se usa de los warps es su **posición**.

**2. Solo los exteriores iluminan una zona.**
Entrar a un interior lo revela a él, no a la ciudad a la que pertenece: en un
warp rando has llegado ahí por una puerta cualquiera. `refreshStats()` en
`app/static/app.js` solo cuenta zonas de mapas con `kind === 'outdoor'`.

**3. Una puerta nunca lleva a su propia casilla.**
`Tracker._detect()` descarta las transiciones donde origen y destino son el
mismo warp del mismo mapa. Sin ese filtro, cualquier hueco en el muestreo
sobre una casilla con puerta inventa un enlace. Lo cubre
`test_un_hueco_en_el_muestreo_no_inventa_una_puerta`.

**4. Cambiar de mapa no es la única señal de transición.**
En el gimnasio de Algaria los teletransportes llevan al **mismo mapa**
(`MAP_MOSSDEEP_CITY_GYM` → `MAP_MOSSDEEP_CITY_GYM`). El detector mira tres
cosas: cambio de mapa, cambio de `warp_id`, o salto de posición imposible.
Quitar cualquiera de las tres pierde casos reales.

---

## Comandos

```bash
# Preparar (una vez, o tras cambiar traducciones / actualizar pokeemerald)
python tools/build_data.py   --pokeemerald ../pokeemerald
python tools/render_maps.py  --pokeemerald ../pokeemerald
python tools/build_layout.py

# Ejecutar
uvicorn app.server:app                  # http://127.0.0.1:8000

# Probar
pytest                                  # 10 tests, sin emulador
python tools/simulate.py                # finge ser mGBA end-to-end
python tools/preview_world.py --scale 16 --out mapa.png
```

El intérprete está en `.venv/Scripts/python.exe` (Windows). Python 3.14,
Pillow 12, numpy 2.5, FastAPI 0.140.

`uvicorn --reload` **no** conviene: el puente TCP se ata al puerto 8765 y un
recargado deja el puerto ocupado. Reiniciar a mano.

---

## Arquitectura

```
mGBA + bridge/pker_bridge.lua       lee gSaveBlock1 cada 4 frames
        │  TCP 127.0.0.1:8765, una línea JSON por lectura
        ▼
app/bridge.py    BridgeServer, hilo aparte, parsea líneas -> Sample
        ▼
app/tracker.py   Tracker.feed(Sample) -> eventos; TODA la lógica está aquí
        ▼
app/state.py     Run: visited / links / specials, guarda en runs/<n>.json
        ▼
app/server.py    FastAPI: API REST + WebSocket (Hub) -> navegador
        ▼
app/static/app.js   lienzo canvas con virtualización y mipmaps
```

`Tracker` no toca sockets ni ficheros: se le pasan `Sample` sueltos. Por eso
se puede probar reproduciendo trazas. **Mantener esa separación**: si hace
falta lógica nueva de detección, va en `tracker.py` con su test, no en
`bridge.py`.

`Hub.broadcast_soon()` existe porque el puente corre en un hilo ajeno al bucle
de asyncio; usa `run_coroutine_threadsafe`.

---

## Datos generados (`data/static/`, no versionados)

| Fichero | Contenido | Lo usa |
|---|---|---|
| `maps.json` | 518 mapas con `(map_group, map_num)`, layout, mapsec, conexiones, nombre | todo |
| `warps.json` | posiciones de los 1313 warps; **el índice ES el warpId** | tracker, API |
| `warps_vanilla.json` | destinos originales — **prohibido usar** | nada |
| `layouts.json` | 441 layouts: tamaño, tilesets, ruta del blockdata | render, layout |
| `tilesets.json` | 75 tilesets: rutas de assets e `is_secondary` | render |
| `metatile_behaviors.json` | los 241 nombres `MB_*` y cuáles son de transición | render |
| `warp_tiles.json` | por layout, casillas con behavior de transición | tracker |
| `world_layout.json` | posición en píxeles de cada mapa en el lienzo | API |

Lienzo resultante: **25456 × 13344 px**. Assets: 1323 PNG, ~15 MB.

---

## Trampas encontradas en los datos de pokeemerald

Están todas resueltas, pero si algo se toca conviene saberlas:

- **El nombre del tileset no da su ruta.** `gTileset_Building` usa
  `gMetatiles_InsideBuilding`. Hay que seguir los campos `.tiles`,
  `.palettes`, `.metatiles` del header, nunca derivar por convención.
- **Los tilesets primarios se declaran en `src/graphics.c`**, no en
  `src/data/tilesets/graphics.h` como los secundarios. Hay que leer los dos.
- **Los tilesets de base secreta comparten `metatiles.bin`** pero cada uno
  tiene su `tiles.png` en una subcarpeta.
- **El símbolo de tiles puede llevar sufijo `Compressed`** o no.
- **El enum de behaviors es anónimo** (`enum { MB_NORMAL, ... }`).
- **Algunos `map.bin` tienen bloques de más.** Solo en layouts sin usar; se
  truncan. Que falten sí es error.
- **Tres conexiones del juego son asimétricas** (Verdanturf/Route116,
  Fallarbor/Route114, Dewford/Route107, 2 metatiles). Produce un solape que
  `build_layout.py` clasifica como esperado porque los mapas son vecinos. **No
  es un bug: está así en el juego original.**
- `dive` y `emerge` son direcciones de conexión que **no** son adyacencia
  espacial (buceo). Se excluyen del ensamblado.
- Hay layouts con `secondary_tileset: "0"` (sin secundario).

---

## Constantes con motivo

| Constante | Valor | Por qué |
|---|---|---|
| `SAVEBLOCK1_PTR` | `0x03005D8C` | puntero a `gSaveBlock1` en Esmeralda USA. El bloque **se mueve**, hay que seguir el puntero. Si la ROM lo desplaza: `bridge/pker_calibrate.lua` |
| `SAMPLE_EVERY` | 4 frames | precisión suficiente para no perder la casilla de la puerta |
| `WARP_SEARCH_RADIUS` | 1 | margen al buscar la puerta de salida |
| `HISTORY_DEPTH` | 12 | muestras que se guardan para mirar hacia atrás |
| `TELEPORT_DISTANCE` | 16 | **deliberadamente alto**: con 5 saltaba en falso |
| `METATILE_ID_MASK` | `0x03FF` | bits 0-9 del blockdata |
| `NUM_METATILES_IN_PRIMARY` | 512 | ≥512 → tileset secundario |
| `NUM_PALS_IN_PRIMARY` | 6 | paletas 0-5 primario, 6-12 secundario |

---

## Formato del render

Metatile de 16×16 = 8 tiles de 8×8: entradas 0-3 capa inferior, 4-7 superior.
Cada entrada u16: tile id bits 0-9, flip X bit 10, flip Y bit 11, paleta bits
12-15. Índice de color 0 = transparente. `tiles.png` es indexado, 16 tiles por
fila.

Se pre-renderizan los 1024 metatiles por par de tilesets (`build_atlas`) y
luego el mapa es una indexación vectorizada de numpy — sin esa caché, 441
mapas serían inviables.

---

## Dónde tocar según qué

| Quiero... | Voy a... |
|---|---|
| cambiar cómo se detectan las puertas | `app/tracker.py` + test en `tests/test_tracker.py` |
| cambiar la disposición del lienzo | `tools/build_layout.py`, luego `preview_world.py` para verlo |
| cambiar el dibujado | `app/static/app.js` (`draw`, `drawMap`, `drawLinks`) |
| añadir datos extraídos | `tools/build_data.py`, con su comprobación de coherencia |
| traducir nombres | `data/i18n/es_overrides.json` + relanzar `build_data.py` |
| soportar otra ROM/randomizer | `SAVEBLOCK1_PTR` en el Lua; los offsets valen para cualquier build de pokeemerald |

---

## Verificación

Los scripts de `tools/` **devuelven código de error** si encuentran
incoherencias. Al añadir extracción, añadir su comprobación: es lo que cazó
que `gTileset_General` había desaparecido del listado.

Al tocar el render o el layout, **mirar el resultado**, no solo que no falle:

```bash
python tools/preview_world.py --scale 16 --out /tmp/check.png
```

Para la interfaz sirve una captura headless con Edge. **Borrar antes
`--user-data-dir`**: una captura con perfil cacheado sirvió un `app.js` viejo
y pareció un bug del código que no existía.

---

## Estado y pendientes

Terminado y verificado sin ROM: extracción, render, ensamblado, puente,
tracker, interfaz, 10 tests en verde.

**Sin validar contra la ROM real** (requiere al usuario):

1. Que `0x03005D8C` valga en la ROM parcheada → si no, `pker_calibrate.lua`.
2. **Que el parche no mueva las posiciones de las puertas.** Todo el
   emparejado depende de ello. Si resultara que sí las mueve, el plan B es
   identificar la puerta por el behavior del metatile pisado: los datos ya
   están en `warp_tiles.json`, solo faltaría la lógica en `_find_exit()`.

Limitaciones asumidas: cargar un savestate puede generar una transición
`script` espuria (inocua, no toca los links); Vuelo y Teletransporte revelan
mapa pero no crean enlaces, que es lo correcto.
