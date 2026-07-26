-- Localiza gSaveBlock1Ptr en la ROM que estes usando.
--
-- Solo hace falta si el puente no detecta bien los mapas, porque la version
-- parcheada haya movido el simbolo. Cargalo en mGBA igual que el puente
-- (Tools > Scripting) con la partida ya empezada, y sigue las instrucciones
-- que va escribiendo en la consola.
--
-- Como funciona: en IWRAM hay muy pocos punteros que apunten a EWRAM y cuyos
-- bytes siguientes formen un (grupo, mapa) plausible. Cruzando un par de
-- puertas, los falsos candidatos se delatan solos porque no cambian cuando
-- cambias de mapa, o cambian a valores imposibles.

local IWRAM_START = 0x03000000
local IWRAM_END   = 0x03008000
local EWRAM_START = 0x02000000
local EWRAM_END   = 0x02040000

-- Emerald (USA). Si la busqueda da otro valor, es el de tu ROM.
local KNOWN_POINTER = 0x03005D8C

local MAX_MAP_GROUP = 33   -- 34 grupos en Esmeralda (0..33)
local MAX_MAP_NUM   = 99
local CHECK_EVERY   = 30   -- frames entre comprobaciones

local candidates = {}
local frame = 0
local epochs = 0

local function readLocation(base)
	return emu:read8(base + 4), emu:read8(base + 5), emu:read8(base + 6)
end

local function plausible(pointer)
	if pointer < EWRAM_START or pointer >= EWRAM_END then return false end
	local group, num = readLocation(pointer)
	return group <= MAX_MAP_GROUP and num <= MAX_MAP_NUM
end

local function scan()
	local found = {}
	for address = IWRAM_START, IWRAM_END - 4, 4 do
		local pointer = emu:read32(address)
		if plausible(pointer) then
			local group, num, warp = readLocation(pointer)
			table.insert(found, {
				address = address, group = group, num = num, warp = warp,
				changes = 0,
			})
		end
	end
	return found
end

local function describe(entry)
	return string.format("0x%08X -> mapa (%d, %d) warp %d",
		entry.address, entry.group, entry.num, entry.warp)
end

local function check()
	local moved = 0
	local survivors = {}

	for _, entry in ipairs(candidates) do
		local pointer = emu:read32(entry.address)
		if plausible(pointer) then
			local group, num, warp = readLocation(pointer)
			if group ~= entry.group or num ~= entry.num then
				entry.changes = entry.changes + 1
				entry.group, entry.num, entry.warp = group, num, warp
				moved = moved + 1
			end
			table.insert(survivors, entry)
		end
		-- Si deja de apuntar a algo plausible, no era el bloque de guardado.
	end

	local dropped = #candidates - #survivors
	candidates = survivors

	if moved > 0 then
		epochs = epochs + 1
		console:log(string.format(
			"--- cambio de mapa %d: %d candidatos se han movido, %d descartados, quedan %d",
			epochs, moved, dropped, #candidates))
		for _, entry in ipairs(candidates) do
			if entry.changes == epochs then
				console:log("  coherente: " .. describe(entry))
			end
		end
		if epochs >= 2 then
			console:log("")
			console:log("Candidatos que han seguido TODOS los cambios de mapa:")
			local best = nil
			for _, entry in ipairs(candidates) do
				if entry.changes == epochs then
					console:log("  " .. string.format("0x%08X", entry.address)
						.. (entry.address == KNOWN_POINTER and "   <-- el valor por defecto" or ""))
					best = best or entry
				end
			end
			if best then
				console:log("")
				console:log("Pon esta direccion en SAVEBLOCK1_PTR de pker_bridge.lua:")
				console:log(string.format("  0x%08X", best.address))
			end
		end
	end
end

local function onFrame()
	frame = frame + 1
	if frame % CHECK_EVERY == 0 then
		check()
	end
end

candidates = scan()
console:log("pkERandAssist: calibracion")
console:log(string.format("  %d candidatos en IWRAM", #candidates))

local defaultOk = false
for _, entry in ipairs(candidates) do
	if entry.address == KNOWN_POINTER then
		defaultOk = true
		console:log("  el valor por defecto responde: " .. describe(entry))
	end
end
if not defaultOk then
	console:log("  ojo: 0x03005D8C NO parece valido en esta ROM")
end
console:log("")
console:log("Cruza dos o tres puertas; ire descartando los falsos candidatos.")

callbacks:add("frame", onFrame)
