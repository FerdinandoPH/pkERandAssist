# Manual de uso

Asistente de mapa para Pokémon Esmeralda con las puertas randomizadas.

Mientras juegas, el asistente lee del emulador dónde estás y va dibujando tu
partida: revela las zonas que pisas sobre un mapa de Hoenn hecho con los
gráficos reales del juego, y une con una línea cada par de puertas que
confirmas.

---

## 1. Antes de empezar

Necesitas tres cosas:

| Qué | Para qué | Dónde |
|---|---|---|
| **Python 3.11+** | mueve todo el asistente | <https://python.org> |
| **mGBA 0.10+** | es el emulador que sabe ejecutar scripts | <https://mgba.io> |
| **pokeemerald** | de ahí salen los gráficos y los datos de mapas | <https://github.com/pret/pokeemerald> |

Sobre `pokeemerald`: es la decompilación del juego. **No hay que compilar
nada**, solo descargarla — el asistente lee de ahí las imágenes de los
tilesets y las coordenadas de cada puerta.

Tu ROM parcheada la pones tú, y el asistente no la toca en ningún momento:
solo lee la memoria del emulador mientras juegas.

---

## 2. Instalación (una sola vez)

Abre una terminal en la carpeta del proyecto.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install pillow numpy fastapi "uvicorn[standard]" pytest
```

En Linux o macOS, la segunda línea es `source .venv/bin/activate`.

Descarga la decompilación **al lado** de la carpeta del proyecto:

```bash
git clone --depth 1 https://github.com/pret/pokeemerald.git ../pokeemerald
```

---

## 3. Preparar los mapas (una sola vez)

Tres comandos, en este orden. Tardan menos de un minuto en total.

```bash
python tools/build_data.py   --pokeemerald ../pokeemerald
python tools/render_maps.py  --pokeemerald ../pokeemerald
python tools/build_layout.py
```

Qué hace cada uno:

1. **`build_data.py`** saca los datos de los mapas y de las puertas.
   Debe decirte `mapas: 518` y `warps: 1313`.
2. **`render_maps.py`** dibuja los 441 mapas del juego a PNG. Es el que más
   tarda (unos 20 segundos) y genera unos 15 MB en `assets/layouts/`.
3. **`build_layout.py`** monta Hoenn entera y coloca los interiores.
   Termina diciendo el tamaño del lienzo: `25456 x 13344 px`.

Si alguno encuentra un problema te lo dice y devuelve error, así que si los
tres terminan en silencio es que ha ido bien.

> `build_layout.py` avisa de seis «conexiones asimétricas en los datos
> originales». **Eso es normal**: tres conexiones entre mapas del juego de
> Nintendo no encajan por dos casillas. No es un fallo.

Si más adelante actualizas `pokeemerald` o cambias las traducciones, vuelve a
lanzar estos tres comandos.

---

## 4. Jugar

Cada vez que te sientes a jugar, tres pasos:

**1. Arranca el asistente.**

```bash
uvicorn app.server:app
```

Déjalo abierto en su terminal.

**2. Abre el mapa** en el navegador: <http://127.0.0.1:8000>

Verás Hoenn a oscuras. Arriba a la derecha pondrá *emulador sin conectar*.

**3. Conecta el emulador.** En mGBA, **con la ROM ya cargada**:

> Tools → Scripting… → File → Load script… → `bridge/pker_bridge.lua`

En la ventana del script debe aparecer `conectado a 127.0.0.1:8765`, y en el
navegador el aviso pasa a **emulador conectado**. La ventana de scripting
puedes cerrarla: el script sigue funcionando.

Ya está. Camina y el mapa se irá abriendo solo.

---

## 5. La pantalla

### El lienzo

- **Izquierda**: Hoenn montada tal cual es en el juego, con las rutas y
  ciudades en su sitio. Debajo, las islas sueltas y las zonas submarinas.
- **Derecha**: todos los interiores, agrupados por la zona a la que pertenecen
  y con su nombre encima.

Un mapa **apagado** es un sitio donde no has estado: ves su silueta pero no lo
que hay dentro. Cuando lo pisas, aparece dibujado.

### Los controles

| Acción | Cómo |
|---|---|
| Acercar y alejar | rueda del ratón |
| Moverse | arrastrar |
| Ver las puertas de un mapa | clic encima |
| Volver a ver todo | botón **Ver todo** |

Al acercarte lo suficiente aparecen los puntos de las puertas: **grises** las
que no has probado, **verdes** las que ya sabes a dónde llevan.

### Las líneas

- **Azul**: has cruzado esa puerta en un sentido.
- **Verde**: la has cruzado en los dos sentidos, así que el par está
  confirmado.

### El panel

- **Ahora mismo**: en qué mapa estás y en qué casilla.
- **Progreso**: zonas y mapas descubiertos, puertas encontradas y cuántas
  están confirmadas de ida y vuelta.
- **Selección**: al pulsar un mapa, la lista de sus puertas y a dónde va cada
  una. El símbolo ⇄ marca las confirmadas en ambos sentidos.
- **Puertas sin probar**: lo que te queda pendiente en sitios que ya conoces.
  Pulsa una entrada y la cámara va allí.
- **Vista**:
  - *Revelar todo el mapa* destapa Hoenn entera. **Es solo para mirar**: no
    te dice a dónde va ninguna puerta, pero te enseña sitios en los que aún
    no has estado.
  - *Dibujar conexiones* oculta las líneas si te molestan.
  - *Seguir al jugador* mantiene la cámara sobre ti. Se apaga solo en cuanto
    arrastras el mapa a mano.
- **Exportar** descarga en JSON todo lo que llevas descubierto, con los
  nombres en claro.

---

## 6. La primera vez: una comprobación

El asistente deduce **por qué puerta has salido** mirando la última casilla
que pisaste. Eso funciona porque el parche cambia a dónde llevan las puertas,
pero no dónde están.

Merece la pena confirmarlo al empezar: cruza tres o cuatro puertas y mira en
el panel si la puerta de origen que aparece es la que de verdad usaste.

Si no cuadrara, dilo: habría que identificar las puertas por el tipo de
casilla pisada en vez de por su posición. Los datos para hacerlo ya están
extraídos.

---

## 7. Si algo no va

### El panel no sale de «emulador sin conectar»

- ¿Está corriendo `uvicorn app.server:app`?
- ¿Cargaste el script **después** de abrir la ROM?
- Mira la ventana de scripting de mGBA: si pone `buscando el servidor`, es que
  el asistente no está levantado.

### Dice que estás en un mapa que no es

La versión parcheada ha movido en memoria el bloque de guardado. Para
encontrar la dirección correcta:

1. Carga `bridge/pker_calibrate.lua` en mGBA igual que el otro script.
2. Cruza dos o tres puertas.
3. En la consola aparecerá algo como
   `Pon esta direccion en SAVEBLOCK1_PTR: 0x03005D8C`.
4. Abre `bridge/pker_bridge.lua`, cambia la línea `local SAVEBLOCK1_PTR` por
   esa dirección y vuelve a cargar el script.

### Aparecen transiciones raras después de cargar un savestate

Es esperado. Al cargar un savestate el juego «salta» sin cruzar ninguna
puerta, y el asistente lo apunta como transición de tipo `script`. **No
estropea las puertas ya confirmadas.**

### El mapa se ve lento

Aleja un poco la vista. Muy cerca y con muchos mapas descubiertos a la vez, el
navegador carga las imágenes a resolución completa.

---

## 8. Otras cosas

### Empezar una partida nueva

Tu progreso está en `runs/default.json`. Para archivarlo, renómbralo (por
ejemplo a `runs/partida-1.json.bak`); el asistente creará uno nuevo al
arrancar. Para vaciarlo sin cerrar nada:

```bash
curl -X POST http://127.0.0.1:8000/api/reset
```

### Nombres en castellano

Los mapas salen en inglés salvo los que estén traducidos en
`data/i18n/es_overrides.json`. Vienen las diez ciudades principales; puedes
añadir lo que quieras siguiendo el mismo formato:

```json
"MAPSEC_DEWFORD_TOWN": "Pueblo Azuliza",
"MAP_ROUTE104": "Ruta 104"
```

Las claves `MAPSEC_*` son zonas y las `MAP_*` mapas concretos. Cuando traduces
una zona, los mapas que empiezan por su nombre se traducen solos: al poner
`MAPSEC_MOSSDEEP_CITY`, el gimnasio pasa a llamarse *Ciudad Algaria - Gym*.

Después de editarlo, vuelve a lanzar `python tools/build_data.py`.

### Ver el asistente sin la ROM

Para probarlo sin tocar el emulador, hay un simulador que se hace pasar por
mGBA y recorre un camino de ejemplo:

```bash
uvicorn app.server:app        # en una terminal
python tools/simulate.py      # en otra
```

### Una imagen del mapa entero

```bash
python tools/preview_world.py --scale 16 --out mapa.png
```

Vuelca todo el lienzo a un PNG, útil para verlo de un vistazo o imprimirlo.
