-- Puente entre mGBA y el asistente de mapa.
--
-- Uso: en mGBA, Tools > Scripting... > File > Load script, y elegir este
-- fichero con la ROM ya cargada. La ventana de scripting puede quedarse
-- abierta o cerrarse: el script sigue corriendo.
--
-- Lee de gSaveBlock1 la posicion del jugador y el mapa en el que esta, y lo
-- manda por TCP al servidor. En Esmeralda el bloque de guardado se mueve por
-- la RAM, asi que hay que seguir el puntero en vez de leer una direccion fija.

local HOST = "127.0.0.1"
local PORT = 8765

-- gSaveBlock1Ptr en Pokemon Esmeralda (USA). Si la ROM parcheada lo desplaza,
-- tools/calibrate.py encuentra el valor bueno y se cambia aqui.
local SAVEBLOCK1_PTR = 0x03005D8C

-- Offsets dentro de SaveBlock1: struct Coords16 pos; struct WarpData location;
local OFFSET_X        = 0x00  -- s16
local OFFSET_Y        = 0x02  -- s16
local OFFSET_GROUP    = 0x04  -- s8
local OFFSET_NUM      = 0x05  -- s8
local OFFSET_WARP     = 0x06  -- s8

local SAMPLE_EVERY   = 4    -- frames entre lecturas
local HEARTBEAT_EVERY = 120 -- frames entre latidos aunque no cambie nada
local RETRY_EVERY    = 180  -- frames entre reintentos de conexion

local EWRAM_START = 0x02000000
local EWRAM_END   = 0x02040000

local socketHandle = nil
local frame = 0
local lastPayload = nil
local lastSent = 0
local nextRetry = 0

local function signed8(value)
	if value >= 0x80 then return value - 0x100 end
	return value
end

local function signed16(value)
	if value >= 0x8000 then return value - 0x10000 end
	return value
end

local function connect()
	local handle, err = socket.connect(HOST, PORT)
	if not handle then
		return nil, err
	end
	socketHandle = handle
	console:log("pkERandAssist: conectado a " .. HOST .. ":" .. PORT)
	return handle
end

local function disconnect(reason)
	if socketHandle then
		pcall(function() socketHandle:close() end)
		socketHandle = nil
		console:log("pkERandAssist: desconectado (" .. tostring(reason) .. ")")
	end
end

local function readState()
	local base = emu:read32(SAVEBLOCK1_PTR)
	-- Antes de cargar partida el puntero aun no apunta a nada util.
	if base < EWRAM_START or base >= EWRAM_END then
		return nil
	end
	return {
		group = signed8(emu:read8(base + OFFSET_GROUP)),
		num   = signed8(emu:read8(base + OFFSET_NUM)),
		warp  = signed8(emu:read8(base + OFFSET_WARP)),
		x     = signed16(emu:read16(base + OFFSET_X)),
		y     = signed16(emu:read16(base + OFFSET_Y)),
	}
end

local function encode(state)
	return string.format(
		'{"map_group":%d,"map_num":%d,"warp_id":%d,"x":%d,"y":%d,"frame":%d}',
		state.group, state.num, state.warp, state.x, state.y, frame)
end

local function onFrame()
	frame = frame + 1

	if not socketHandle then
		if frame >= nextRetry then
			nextRetry = frame + RETRY_EVERY
			connect()
		end
		return
	end

	if frame % SAMPLE_EVERY ~= 0 then
		return
	end

	local state = readState()
	if not state then
		return
	end

	local payload = encode(state)
	-- Se manda solo lo que cambia; el latido evita que el servidor crea que
	-- el emulador se ha caido cuando estas quieto.
	local changed = payload ~= lastPayload
	if not changed and (frame - lastSent) < HEARTBEAT_EVERY then
		return
	end

	local ok, err = socketHandle:send(payload .. "\n")
	if not ok then
		disconnect(err)
		nextRetry = frame + RETRY_EVERY
		return
	end
	lastPayload = payload
	lastSent = frame
end

callbacks:add("frame", onFrame)
callbacks:add("stop", function() disconnect("emulacion detenida") end)

console:log("pkERandAssist: script cargado, buscando el servidor en "
	.. HOST .. ":" .. PORT)
connect()
