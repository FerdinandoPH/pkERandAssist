# Cómo está hecho

Explicación de cómo funciona el asistente por dentro: qué problema resuelve
cada pieza, por qué está resuelta así y qué cosas resultaron no ser como
parecían.

---

## El problema

En una partida con las puertas randomizadas, el juego sigue funcionando igual
pero el mapa mental que tienes no sirve para nada: entras al centro Pokémon de
Pueblo Escaso y sales en el gimnasio de Arrecípolis. La única forma de avanzar
es ir apuntando qué puerta lleva a cuál.

Hacen falta tres cosas para automatizarlo:

1. **Saber dónde estás** en cada momento, en vivo.
2. **Tener los mapas dibujados**, para enseñarlos.
3. **Deducir qué puerta has usado**, que es la parte que nadie te dice.

Las tres tienen truco, y la tercera más de lo que parece.

---

## 1. Saber dónde estás: leer la memoria del emulador

Un juego de Game Boy Advance guarda su estado en la RAM de la consola. Si
puedes leer esa RAM mientras el juego corre, sabes exactamente qué está
pasando.

mGBA permite ejecutar pequeños programas en Lua que corren *dentro* del
emulador y pueden leer cualquier dirección de memoria. Eso resuelve el acceso.
La pregunta es **qué** dirección leer.

### El bloque de guardado se mueve

En Esmeralda, la estructura con los datos de la partida (`gSaveBlock1`) no
está en un sitio fijo: el juego la reubica en memoria. Leer una dirección fija
daría basura la mitad del tiempo.

Lo que sí es fijo es un **puntero** a esa estructura, en `0x03005D8C`. Así que
se lee en dos pasos: primero el puntero, y luego los datos donde éste apunte.

```lua
local base = emu:read32(0x03005D8C)   -- dónde está ahora el bloque
local grupo = emu:read8(base + 4)     -- y ahí dentro, el mapa
```

Los primeros bytes del bloque son justo lo que interesa:

| Posición | Contenido |
|---|---|
| `+0x00` | coordenada X del jugador |
| `+0x02` | coordenada Y |
| `+0x04` | grupo de mapa |
| `+0x05` | número de mapa dentro del grupo |
| `+0x06` | **por qué puerta entraste** al mapa actual |

Ese último campo es media solución del problema: el juego sí guarda por qué
puerta *entraste*. Lo que no guarda en ningún sitio es por cuál *saliste*.

### El script y el servidor

El Lua lee esos cinco valores cada 4 fotogramas y, si algo ha cambiado, manda
una línea de texto por una conexión de red local al asistente en Python. Solo
manda lo que cambia, más un latido cada dos segundos para que el asistente
sepa que el emulador sigue vivo.

Es sencillo a propósito: cuanto menos haga el script dentro del emulador,
menos puede estropear la partida.

---

## 2. Tener los mapas dibujados

La idea inicial era sacar los gráficos de la ROM. Resultó innecesario: existe
**pokeemerald**, un proyecto que ha reconstruido el código fuente del juego a
partir del cartucho, y que incluye los gráficos ya en formato normal.

No hay que compilar nada. Los ficheros están ahí y basta leerlos.

### Cómo se dibuja un mapa de Game Boy Advance

Una consola de 2001 no puede guardar cada mapa como una imagen: no cabría. Usa
tres niveles de reutilización:

1. **Tiles**: cuadraditos de 8×8 píxeles. Todos los del juego caben en una
   hoja de dibujo por decorado.
2. **Metatiles**: bloques de 16×16 hechos con 8 tiles — cuatro abajo y cuatro
   encima. La doble capa permite, por ejemplo, poner una maceta (capa
   superior) sobre un suelo de madera (capa inferior) sin duplicar dibujos.
3. **Mapa**: una rejilla que dice qué metatile va en cada casilla.

Cada casilla del mapa es un número de 16 bits, del que solo los 10 primeros
son el metatile; el resto guarda si se puede pisar y a qué altura está.

Reconstruir la imagen es deshacer ese empaquetado: para cada casilla se busca
su metatile, para cada metatile sus ocho tiles, y cada tile se pinta con la
paleta de colores que le toque, dándole la vuelta en horizontal o vertical si
lo pide.

Con 441 mapas eso son millones de operaciones, así que se hace en dos fases:
primero se dibujan una sola vez los 1024 metatiles de cada juego de decorados
y se guardan en memoria, y después cada mapa es solo copiar bloques ya hechos.
Los 441 mapas salen en unos 20 segundos.

### Miniaturas

Un mapa a tamaño real puede ocupar 1000×1000 píxeles. Al ver Hoenn entera de
lejos, cargar cientos de imágenes así ahogaría al navegador para acabar
pintándolas del tamaño de un sello.

Por eso de cada mapa se guardan tres versiones: la normal, una a un cuarto y
otra a un dieciseisavo. El navegador elige según lo cerca que estés. Es la
misma idea que usan los mapas de internet cuando cambias de zoom.

---

## 3. Montar Hoenn

Los mapas del juego están sueltos: no hay ningún fichero con «el mapa de la
región». Lo que sí hay, en cada mapa, es una lista de sus vecinos:

```json
{"map": "MAP_ROUTE101", "offset": 0, "direction": "up"}
```

«La Ruta 101 está justo encima de mí, sin desplazamiento lateral».

Con eso se puede montar la región como un puzle: se empieza por Pueblo Escaso
en el origen, se colocan sus vecinos alrededor, luego los vecinos de esos, y
así hasta que no quede nadie. Es un recorrido en anchura, el mismo algoritmo
que usa un GPS para explorar calles.

El resultado es Hoenn exacta, casilla a casilla, no una aproximación.

### Lo que no encaja

Dos cosas aparecen al montarlo:

**Sobran trozos.** No todo está conectado: la Isla Espejismo, la Zona de
Combate o las zonas submarinas no tienen vecinos por tierra. El recorrido
encuentra 25 grupos separados. El más grande (49 mapas) es el continente y
manda; los otros 24 se colocan ordenaditos debajo.

**Hay tres conexiones que se contradicen.** Pueblo Verdegal dice que la Ruta
116 está dos casillas más arriba de donde la Ruta 116 dice que está. Lo mismo
pasa en otros dos sitios. No es un error de lectura: **está así en el juego
original**. Nintendo nunca lo notó porque el juego solo usa una conexión a la
vez, la del lado por el que estás saliendo.

Se deja como está y se documenta. Lo que sí hace el programa es distinguir
entre ese solape (esperado, entre mapas que son vecinos) y un solape de
verdad, que sería un fallo del montaje.

### Y los interiores, ¿dónde van?

Un interior no tiene sitio en la geografía: la casa de Brendan no está «al
lado» de nada, está *dentro* de un edificio de Pueblo Escaso.

La solución copia la de los mapas interactivos de Esmeralda: los interiores se
agrupan por la zona a la que pertenecen y se colocan en una franja a la
derecha, con un rótulo por zona.

Para que no salga una tira interminable de 43 000 píxeles, se empaquetan en
dos niveles: primero los interiores dentro del bloque de su zona, y luego los
bloques de zona entre ellos. El lienzo pasa de una columna larguísima a un
mosaico de 25456 × 13344, y las zonas van ordenadas de norte a sur siguiendo
la geografía.

---

## 4. La parte difícil: deducir la puerta

Aquí está el meollo. El juego dice por qué puerta **entraste**, pero no por
cuál **saliste**. Y sin las dos mitades no hay pareja que apuntar.

La solución es mirar dónde estabas justo antes de desaparecer. En Pokémon las
puertas se activan al pisarlas, así que la última casilla en la que te vieron
en el mapa anterior *es* la puerta que usaste. Y las posiciones de todas las
puertas del juego están en los datos de pokeemerald.

El razonamiento completo:

1. Detecto que has cambiado de sitio.
2. Miro hacia atrás en las últimas lecturas hasta encontrar la última casilla
   del mapa anterior.
3. Busco si en esa casilla (o pegada a ella) hay una puerta. Esa es la salida.
4. La entrada me la dice el juego directamente.
5. Apunto la pareja.

Cuando más adelante haces el camino inverso y las dos mitades encajan, el par
pasa a **confirmado en ambos sentidos** y se pinta en verde.

### Detectar que te has movido no es tan obvio

La primera versión disparaba al cambiar de mapa. Parece razonable y es
insuficiente: **en el gimnasio de Algaria los teletransportes te dejan en el
mismo mapa**. Las plataformas del suelo van del gimnasio al gimnasio. Ese
detector no se enteraría de ninguna.

Así que hay tres señales, y basta con una:

- has cambiado de mapa,
- ha cambiado la puerta por la que entraste (aunque el mapa sea el mismo),
- o has aparecido a una distancia imposible de recorrer andando.

Esto se descubrió mirando de verdad los datos de los mapas, no razonando desde
el sillón.

### Las puertas que no son puertas

No todo lo que te mueve está en la lista de puertas. Hay:

- **Agujeros en el suelo.** En la Torre Celeste el suelo se rompe y caes al
  piso de abajo. Hay 94 casillas así en el juego y ninguna es una «puerta».
- **Conexiones entre rutas.** Caminar de Pueblo Escaso a la Ruta 101 no es una
  puerta, es que los mapas son vecinos.
- **Guiones del juego.** Vuelo, Teletransporte, Cuerda Huida, las escenas de
  la historia.

Para los agujeros hay un truco: además de las coordenadas, cada casilla del
juego tiene un *tipo* (puerta animada, escalera, suelo agrietado, cinta
transportadora...). Ese dato ya se lee al dibujar los mapas, así que se
aprovecha: si te mueves desde una casilla que no es puerta, se mira su tipo.
Si es un agujero, se apunta como tal.

Las conexiones se distinguen porque el mapa nuevo está en la lista de vecinos
del anterior. Y lo que no es ninguna de las dos cosas se marca como «guion»:
revela el mapa nuevo, pero no inventa ninguna conexión entre puertas. Que es
lo correcto: un Vuelo no es una puerta.

### El fallo que encontró el simulador

Antes de tocar la ROM se escribió un programa que se hace pasar por el
emulador y reproduce un recorrido inventado. La primera ejecución sacó esto:

```
Pueblo Escaso puerta 1  <->  Pueblo Escaso puerta 1
```

Una puerta que lleva a sí misma. Imposible: si una puerta te dejara sobre su
propia casilla, entrarías en un bucle infinito.

Lo que había pasado: el recorrido de prueba saltaba de una casilla a otra
lejana, el detector lo tomó por un teletransporte, buscó una puerta cerca del
origen y encontró una. Salieron dos arreglos:

1. **Rechazar por imposible** cualquier pareja donde la salida y la entrada
   sean la misma puerta del mismo mapa.
2. **Subir mucho el umbral** de «salto imposible», de 5 casillas a 16. Con un
   umbral bajo, cualquier hueco en las lecturas —un savestate, un tirón del
   emulador— se convertía en una puerta inventada.

Este fallo no lo habrían encontrado los tests, porque los tests comprueban lo
que uno ya pensó que podía fallar. Lo encontró darle al programa datos
imperfectos y mirar el resultado.

---

## 5. Enseñarlo

El mapa completo son 25456 × 13344 píxeles: unos 340 megapíxeles. No cabe como
imagen ni de lejos.

La solución es la de cualquier mapa de internet: **no dibujar lo que no se
ve**. En cada repintado se calcula qué trozo del mundo cae dentro de la
ventana, se dibujan solo los mapas que caen ahí, y se usa la miniatura que
corresponda al zoom. De 518 mapas, en pantalla suele haber diez o veinte.

Las imágenes se piden solo cuando hacen falta, y una vez cargadas se quedan en
memoria.

### La niebla

Un mapa que no has pisado se dibuja como un rectángulo oscuro con su contorno.
Así se reconoce la silueta de Hoenn desde el principio —cosa que ya sabías— sin
enseñar nada que no hayas descubierto.

Las líneas entre puertas se dibujan curvadas a propósito: en un warp rando dos
puertas emparejadas suelen estar en puntas opuestas del lienzo, y con líneas
rectas los cruces serían imposibles de seguir.

---

## 6. Lo que se decidió no hacer

**No usar los destinos originales.** Los datos de pokeemerald incluyen a dónde
llevaba cada puerta en el juego sin parchear. Están extraídos, pero guardados
aparte y sin usar: enseñarlos arruinaría la partida. Solo se usan las
*posiciones* de las puertas, que el parche no cambia.

**No iluminar una ciudad por entrar a un interior suyo.** Entrar al centro
Pokémon de Ciudad Férrica no significa haber llegado a Ciudad Férrica: has
aparecido ahí por una puerta cualquiera. Solo pisar el exterior cuenta como
progreso.

**No poner los interiores en un grafo automático.** Se probó la idea de un
grafo de nodos que se recoloca solo, pero un dibujo que cambia cada vez que
descubres algo no sirve para orientarse. Los interiores tienen un sitio fijo
desde el principio, y lo único que cambia es que se encienden.

---

## 7. Cómo se comprobó que funciona

Sin la ROM parcheada delante, había que verificar cada pieza por separado:

- **Los gráficos**, mirándolos. Se renderizó Pueblo Escaso y se comparó con el
  juego: si las paletas o los volteos estuvieran mal, se vería al instante.
- **El montaje de Hoenn**, volcando el mapa entero a un PNG. La silueta de la
  región se reconoce, así que las conexiones se están aplicando bien.
- **La lógica de las puertas**, con diez tests que reproducen recorridos
  grabados sin necesidad de emulador. Cubren los casos con trampa: los
  teletransportes del gimnasio de Algaria, los agujeros de la Torre Celeste,
  las conexiones entre rutas y los huecos en las lecturas.
- **El sistema entero**, con el simulador que se hace pasar por mGBA. Es el
  que encontró el fallo de la puerta que llevaba a sí misma.
- **La interfaz**, tomando capturas de pantalla del navegador y mirándolas.

Queda una cosa que no se puede comprobar sin la ROM: que el parche no mueva
las posiciones de las puertas. Todo el emparejado depende de eso. Si resultara
que sí las mueve, el plan B ya tiene los datos preparados: identificar cada
puerta por el tipo de casilla en vez de por dónde está.
