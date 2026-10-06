-- Civ6Ai seat roles and host settings.
--
-- Host settings come from one file, InGame/Civ6Ai_Paths.lua, which
-- scripts/install_mod.py writes into the host's installed copy. The shipped
-- package carries a neutral stub, so a friend's PC runs with defaults: it never
-- drives a seat, because only the network host runs the bridge.
--
-- Seat roles come from game state. Live install writes Autotest = 1 so the
-- model plays every managed major, including the local human, in SP and LAN.
-- --no-autotest leaves the local human for you to play.
Civ6Ai_Config = Civ6Ai_Config or {}

local function setting(name)
  if Civ6Ai_Paths == nil then
    return nil
  end
  local value = Civ6Ai_Paths[name]
  if value == "" then
    return nil
  end
  return value
end

local function flag(name)
  return tonumber(setting(name)) == 1
end

function Civ6Ai_Config.IsNetworkGame()
  return GameConfiguration ~= nil and GameConfiguration.IsNetworkMultiplayer ~= nil
    and GameConfiguration.IsNetworkMultiplayer() == true
end

function Civ6Ai_Config.Initialize()
  Civ6Ai_Config._managedSeats = Civ6Ai_Config._ParseSeatList(setting("ManagedSeats"))
  Civ6Ai_Config._autotest = flag("Autotest")
  Civ6Ai_Config._seatExperiment = flag("SeatExperiment")
  Civ6Ai_Config._fastEndTurn = flag("FastEndTurn")
  Civ6Ai_Config._root = setting("Civ6AiRoot") or "civ6ai"
  Civ6Ai_Config._sessionId = setting("SessionId") or ""
  Civ6Ai_Config._enableSinglePlayerChat = setting("EnableSinglePlayerChat") == nil or flag("EnableSinglePlayerChat")
  Civ6Ai_Config._mpTest = flag("MpTest")
  Civ6Ai_Config._seatSnapshotAt = Civ6Ai_Config._ParseSeatSnapshotAt(setting("SeatSnapshotAt"))
  local managed = {}
  for _, seat in ipairs(Civ6Ai_Config.ManagedSeatsList()) do
    table.insert(managed, tostring(seat))
  end
  Civ6Ai_Util.Log(
    "config|root=" .. tostring(Civ6Ai_Config._root)
      .. "|network=" .. tostring(Civ6Ai_Config.IsNetworkGame())
      .. "|host_pc=" .. tostring(Civ6Ai_Config.IsHostPc())
      .. "|autotest=" .. tostring(Civ6Ai_Config._autotest)
      .. "|managed=" .. table.concat(managed, ",")
      .. "|sidecar_live=" .. tostring(Civ6Ai_Config.IsSidecarLive())
      .. "|fast_end_turn=" .. tostring(Civ6Ai_Config.IsFastEndTurn())
      .. "|sp_chat=" .. tostring(Civ6Ai_Config.EnableSinglePlayerChat())
      .. "|mp_test=" .. tostring(Civ6Ai_Config.IsMpTest())
      .. "|seat_snapshot_at=" .. tostring(Civ6Ai_Config.SeatSnapshotAt())
      .. "|session=" .. tostring(Civ6Ai_Config.SessionId())
  )
end

function Civ6Ai_Config._ParseSeatList(raw)
  local seats = {}
  if raw == nil then
    return seats
  end
  for token in string.gmatch(tostring(raw), "([^,]+)") do
    local seat = tonumber(token)
    if seat ~= nil then
      seats[seat] = true
    end
  end
  return seats
end

-- When managed AI seats are snapshotted (docs/REAL_TEST.md "Seat timing"):
--   host_end   (default) when the host seat is done with its turn, so the AI
--              seats see the host's moves; their orders play at their next
--              turn start (single player: the same game turn).
--   turn_start at the host seat's turn start, in parallel with the host's own
--              decision (faster; the host's moves of this turn are not seen).
Civ6Ai_Config.SEAT_SNAPSHOT_AT = { host_end = true, turn_start = true }

function Civ6Ai_Config._ParseSeatSnapshotAt(raw)
  local value = string.lower(tostring(raw or ""))
  if Civ6Ai_Config.SEAT_SNAPSHOT_AT[value] then
    return value
  end
  return "host_end"
end

function Civ6Ai_Config.SeatSnapshotAt()
  return Civ6Ai_Config._seatSnapshotAt or Civ6Ai_Config._ParseSeatSnapshotAt(setting("SeatSnapshotAt"))
end

function Civ6Ai_Config.IsAutotest()
  return Civ6Ai_Config._autotest == true
end

function Civ6Ai_Config.IsSeatExperiment()
  return Civ6Ai_Config._seatExperiment == true
end

-- A seat a person plays. Autotest treats the local human as model-driven, so
-- that seat does not count as human.
function Civ6Ai_Config.IsHumanSeat(playerID)
  local player = Players[playerID]
  if player == nil or not player:IsHuman() then
    return false
  end
  if Civ6Ai_Config.IsAutotest() then
    return false
  end
  return true
end

-- A seat the model drives: a living major that no person plays. An empty
-- ManagedSeats list means every such major (and, in autotest, the local human).
-- A comma list still restricts to those seats when you want a subset.
function Civ6Ai_Config.IsManagedSeat(playerID)
  local player = Players[playerID]
  if player == nil or not player:IsAlive() or not player:IsMajor() then
    return false
  end
  if Civ6Ai_Config.IsHumanSeat(playerID) then
    return false
  end
  if next(Civ6Ai_Config._managedSeats) == nil then
    return true
  end
  return Civ6Ai_Config._managedSeats[playerID] == true
end

function Civ6Ai_Config.ManagedSeatsList()
  local seats = {}
  for i = 0, 63 do
    if Civ6Ai_Config.IsManagedSeat(i) then
      table.insert(seats, i)
    end
  end
  return seats
end

function Civ6Ai_Config.IsFastEndTurn()
  if Civ6Ai_Config.IsSidecarLive() then
    return false
  end
  return Civ6Ai_Config._fastEndTurn == true
end

function Civ6Ai_Config.EnableSinglePlayerChat()
  return Civ6Ai_Config._enableSinglePlayerChat == true
end

-- Host PC setting: run the scripted two-PC multiplayer test (Civ6Ai_MpTest).
function Civ6Ai_Config.IsMpTest()
  return Civ6Ai_Config._mpTest == true
end

-- True on the PC that hosts a network game (and always outside network games).
-- Civ6 names this Network.IsGameHost() (Civ5's Network.IsSessionHost does not
-- exist in Civ6, which made every PC think it was a client).
function Civ6Ai_Config._IsNetworkHost()
  if Network == nil then
    return false
  end
  for _, name in ipairs({ "IsGameHost", "IsNetSessionHost", "IsSessionHost" }) do
    local fn = Network[name]
    if fn ~= nil then
      local ok, v = pcall(fn)
      if ok and v ~= nil then
        return v == true
      end
    end
  end
  return false
end

function Civ6Ai_Config.IsHostPc()
  if Civ6Ai_Config.IsNetworkGame() then
    return Civ6Ai_Config._IsNetworkHost()
  end
  return true
end

-- The bridge (snapshot, model, orders) runs for managed seats on the host PC only.
function Civ6Ai_Config.ShouldRunBridge(playerID)
  return Civ6Ai_Config.IsManagedSeat(playerID) and Civ6Ai_Config.IsHostPc()
end

function Civ6Ai_Config.RootDir()
  return Civ6Ai_Config._root
end

function Civ6Ai_Config.SessionId()
  return Civ6Ai_Config._sessionId or ""
end

function Civ6Ai_Config.SidecarTimeout()
  return tonumber(setting("SidecarTimeoutSeconds")) or 180
end

function Civ6Ai_Config.PythonExe()
  return setting("Python") or "python"
end

function Civ6Ai_Config.RepoRoot()
  return setting("Repo") or ""
end

function Civ6Ai_Config.SidecarScript()
  return setting("SidecarScript") or "sidecar/run_civ6.py"
end

function Civ6Ai_Config.IsSidecarLive()
  return flag("SidecarLive")
end

function Civ6Ai_Config.AutotestStopTurn()
  return tonumber(setting("AutotestStopTurn")) or 50
end

function Civ6Ai_Config.PersonalityPath(playerID)
  local repo = Civ6Ai_Config.RepoRoot()
  if repo == "" then
    return ""
  end
  return Civ6Ai_Util.JoinPath(repo, "fixtures/civ6/ai_player_" .. tostring(playerID) .. "_personality.json")
end
