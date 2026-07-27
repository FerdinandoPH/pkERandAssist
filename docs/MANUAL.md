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

Descarga la decompilación **al lado** de la carpeta del proyecto:

```bash
git clone --depth 1 https://github.com/pret/pokeemerald.git ../pokeemerald
```

Y ya está: el resto lo hace el propio asistente la primera vez que lo abres.

> **Si prefieres montarlo a mano** (o el lanzador te da problemas), abre una
> terminal en la carpeta del proyecto:
>
> ```bash
> python -m venv .venv
> .venv\Scripts\activate                  # Windows
> source .venv/bin/activate               # Linux o macOS
> pip install -r requirements.txt
> ```

---

## 3. Preparar los mapas (una sola vez)

**No hace falta que hagas nada aquí**: la primera vez que abras el asistente
(paso 4) los prepara solo. Esta sección explica qué está pasando mientras
tanto, y cómo lanzarlo por separado si quieres.

Un solo comando. Tarda menos de un minuto.

```bash
python tools/setup.py
```

Comprueba que tienes las dependencias, busca el clon de `pokeemerald` al lado
de la carpeta del proyecto y, si no lo encuentra, te pide la ruta. Después
encadena los tres pasos enseñando el progreso de cada uno. Si lo vuelves a
lanzar, salta lo que ya esté hecho; con `--force` lo rehace todo.

Por dentro son estos tres comandos, que también puedes lanzar por separado:

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

**1. Arranca el asistente.** Doble clic en:

| Windows | Linux o macOS |
|---|---|
| `Iniciar.bat` | `iniciar.sh` |

Se abre una ventana negra que va contando lo que hace. **La primera vez** crea
el entorno, instala las dependencias y prepara los mapas (ahí es donde puede
pedirte la ruta de `pokeemerald`: la pegas y pulsas Enter); tarda un par de
minutos. Las siguientes veces arranca directamente.

Deja esa ventana abierta mientras juegas: es el asistente. Para cerrarlo,
Ctrl+C ahí dentro.

> En Linux, si el doble clic no hace nada, el archivo no tiene permiso de
> ejecución: `chmod +x iniciar.sh`. Desde terminal, `./iniciar.sh`.
>
> Lanzarlo a mano equivale a `python launcher.py`, y este a su vez a activar
> el entorno y ejecutar `uvicorn app.server:app`. Acepta `--port 8001` si el
> puerto está ocupado (aunque él solo busca el siguiente libre),
> `--no-browser` y `--force-setup` para regenerar los mapas.

**2. Abre el mapa** en el navegador: <http://127.0.0.1:8000>

Se abre solo al arrancar. Verás Hoenn a oscuras y, arriba a la derecha,
*emulador sin conectar*.

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
que hay dentro. Cuando lo pisas, aparece dibujado. (Con el modo *Mundo
visible*, que se explica más abajo, lo ves desde el principio pero atenuado.)

### Los controles

| Acción | Cómo |
|---|---|
| Acercar y alejar | rueda del ratón |
| Moverse | arrastrar |
| Ver las puertas de un mapa | clic encima |
| **Ir al otro lado de una puerta** | clic en su punto verde |
| Volver a ver todo | botón **Ver todo** |

Al acercarte lo suficiente aparecen los puntos de las puertas: **grises** las
que no has probado, **verdes** las que ya sabes a dónde llevan.

### Saltar de un extremo a otro

Acerca hasta que se vean los puntos y pon el ratón sobre uno **verde**: se
resalta él, se resalta su línea y se marca también el punto del otro extremo,
así que ves a dónde vas antes de pulsar. Al hacer clic, la cámara viaja hasta
allí; si el salto es largo se aleja por el camino y vuelve a acercarse, para
que no pierdas el sentido de la distancia. Como al llegar sigues viendo los
puntos, puedes encadenar saltos e ir recorriendo la cadena de puertas.

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
  - *Modo del mapa* elige entre las dos formas de jugar:
    - **Exploración**: el terreno aparece según lo pisas. Es lo de siempre.
    - **Mundo visible**: Hoenn entera se ve desde el principio, pero **lo que
      no has pisado sale atenuado** y se ilumina al llegar. Sirve para
      orientarte si ya te sabes el mapa. En los dos modos las puertas y sus
      conexiones se descubren igual: el modo **no destripa nada**, ni siquiera
      te enseña dónde hay puertas en los sitios donde no has estado.
  - *Dibujar conexiones* oculta las líneas si te molestan.
  - *Seguir al jugador* acerca la cámara y te sigue a ti mientras andas. Se
    apaga solo si arrastras el mapa o pulsas *Ver todo*; hacer zoom con la
    rueda **no** lo apaga, porque mirar más de cerca no es dejar de seguirte.
  - Las tres se recuerdan para la próxima vez que abras el asistente.
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

### La ventana del lanzador se cierra o se queda en un error

Lee el mensaje: está escrito para eso y termina diciendo qué hacer. Los tres
habituales:

- **«No encuentro Python instalado»** — instálalo desde <https://python.org>
  y, en Windows, marca *Add Python to PATH*.
- **«No he podido crear el entorno virtual»** — en Debian o Ubuntu falta el
  paquete: `sudo apt install python3-venv`.
- **«La preparación de los mapas no ha terminado bien»** — casi siempre es que
  no encuentra el clon de `pokeemerald` (sección 2).

Si el lanzador dejó los mapas a medias (por ejemplo, cerraste la ventana
mientras los generaba), vuelve a arrancarlo: lo detecta y los rehace.

### El panel no sale de «emulador sin conectar»

- ¿Está abierta la ventana del asistente (`Iniciar.bat` / `iniciar.sh`)?
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

### Cruzo una puerta y no aparece la línea

Primero, comprueba que sea una puerta de verdad: caminar de una ruta a otra, o
caer por un agujero, revela el mapa nuevo pero **no** dibuja línea, porque no
hay dos puertas que unir. Vuelo y Teletransporte, igual.

Si era una puerta y aun así no aparece, se puede grabar lo que manda el
emulador y mirarlo después. Arranca el asistente con la traza puesta:

```bash
python launcher.py --trace
```

Juega y vuelve a cruzar esa puerta, cierra el asistente con Ctrl+C y pasa la
grabación por:

```bash
python tools/replay.py runs/trazas/traza-*.jsonl --sospechosas
```

Lista los cambios de mapa que no acabaron registrados, con la posición y el
`warp_id` de cada uno. Eso es exactamente lo que hace falta para arreglarlo, y
la grabación no lleva nada de tu partida más que por dónde has ido pasando.

### Aparecen transiciones raras después de cargar un savestate

Es esperado si el savestate te deja en otro mapa: el juego «salta» sin cruzar
ninguna puerta, y el asistente lo apunta como transición de tipo `script`. **No
estropea las puertas ya confirmadas.** Dentro del mismo mapa no apunta nada.

### El mapa se ve lento

Aleja un poco la vista. Muy cerca y con muchos mapas descubiertos a la vez, el
navegador carga las imágenes a resolución completa.

---

## 8. Otras cosas

### Varias partidas a la vez

El apartado **Partida** del panel lo gestiona todo, sin tocar ficheros:

- **Nueva** empieza una partida en blanco y se cambia a ella.
- El desplegable cambia entre las que tengas, con su progreso debajo.
- **Renombrar** te deja llamarlas por la seed, no por un número.
- **Borrar** pide confirmación diciéndote cuánto progreso pierdes.
- **Guardar copia** descarga la partida entera, y **Importar** la recupera.
  Es el formato bueno para respaldar o compartir: el botón *Exportar* de más
  abajo da un informe legible, pensado para leerlo, que no sirve para volver.

Cada partida vive en su `runs/<nombre>.json`. Cambiar de partida mientras
juegas es seguro: el asistente olvida por dónde ibas, de modo que no se
inventa una puerta entre el último sitio de una y el primero de la otra.

Para vaciar la partida actual sin crear otra:

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
