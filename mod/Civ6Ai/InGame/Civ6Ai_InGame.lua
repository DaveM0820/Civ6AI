-- Civ6Ai InGame entry — single Lua context; include modules in dependency order.
Civ6Ai_InGame = Civ6Ai_InGame or {}
include("Civ6Ai_Util.lua")
include("Civ6Ai_Paths.lua")
include("Civ6Ai_Config.lua")
include("Civ6Ai_Snapshot.lua")
include("Civ6Ai_Production.lua")
include("Civ6Ai_Apply.lua")
include("Civ6Ai_OrderChannel.lua")
include("Civ6Ai_MpTest.lua")
include("Civ6Ai_Bridge.lua")
include("Civ6Ai_SeatExperiment.lua")
include("Civ6Ai_Autotest.lua")
include("Civ6Ai_HostChannel.lua")
include("Civ6Ai_Chat.lua")

function Civ6Ai_OnLocalPlayerTurnBegin()
  -- STABLE: autotest first-turn pulse entry (do not change when fixing apply/inject).
  if not Civ6Ai_Config.IsAutotest() then
    return
  end
  if not Civ6Ai_Bridge.IsLoadScreenClosed() then
    return
  end
  local playerID = Game.GetLocalPlayer()
  if playerID == nil or playerID < 0 then
    return
  end
  if not Civ6Ai_Config.IsManagedSeat(playerID) then
    return
  end
  local turn = Game.GetCurrentGameTurn()
  -- LocalPlayerTurnBegin can fire repeatedly within one turn; log it once per turn.
  Civ6Ai_Bridge._LogOnce(
    "local_turn_begin|" .. tostring(playerID) .. "|" .. tostring(turn),
    "autotest|local_turn_begin|player=" .. tostring(playerID) .. "|turn=" .. tostring(turn)
  )
  Civ6Ai_InGame.PulseAfterTurnStart(playerID, turn)
end

-- LocalPlayerTurnBegin fires before the game restores the seat's movement
-- (GameCore PlayerTurnStartComplete comes later). Snapshotting then showed every
-- unit that moved last turn with 0 moves and no legal orders, so P0's units only
-- acted every other turn. Wait for the GameCore mark; a loaded save may never
-- send it for the current turn, so pulse anyway after a few seconds.
Civ6Ai_InGame.TURN_START_WAIT_SECONDS = 8

function Civ6Ai_InGame._TurnStartDone(playerID, turn)
  local shared = ExposedMembers ~= nil and ExposedMembers.Civ6Ai or nil
  if shared == nil then
    return true
  end
  local marks = shared.TurnStartComplete
  if marks == nil then
    return false
  end
  return marks[playerID] ~= nil and marks[playerID] >= turn
end

-- Gameplay LuaEvents often do not reach InGame in a network game. Gameplay still
-- writes ExposedMembers.Civ6Ai.TurnStartComplete; pulse from that mark.
function Civ6Ai_InGame._WatchTurnStarts()
  if Game == nil or Game.GetCurrentGameTurn == nil or Civ6Ai_Config == nil then
    return
  end
  if Civ6Ai_Config.IsHostPc ~= nil and not Civ6Ai_Config.IsHostPc() then
    return
  end
  if Civ6Ai_Config.ManagedSeatsList == nil then
    return
  end
  local turn = Game.GetCurrentGameTurn()
  local marks = ExposedMembers ~= nil and ExposedMembers.Civ6Ai ~= nil and ExposedMembers.Civ6Ai.TurnStartComplete or nil
  if marks == nil then
    return
  end
  for _, playerID in ipairs(Civ6Ai_Config.ManagedSeatsList()) do
    if marks[playerID] == turn then
      if Civ6Ai_Config.ShouldRunBridge == nil or Civ6Ai_Config.ShouldRunBridge(playerID) then
        Civ6Ai_InGame.PulseAfterTurnStart(playerID, turn)
      end
    end
  end
end

function Civ6Ai_InGame.PulseAfterTurnStart(playerID, turn)
  if Civ6Ai_InGame._TurnStartDone(playerID, turn) then
    Civ6Ai_Bridge.RunTurnPulse(playerID)
    return
  end
  Civ6Ai_InGame._waitingTurnStart = Civ6Ai_InGame._waitingTurnStart or {}
  local key = tostring(playerID) .. "|" .. tostring(turn)
  if Civ6Ai_InGame._waitingTurnStart[key] then
    return
  end
  Civ6Ai_InGame._waitingTurnStart[key] = true
  local started = Civ6Ai_Bridge._WallClock()
  local ticks = 0
  Civ6Ai_Util.ScheduleTick(function()
    ticks = ticks + 1
    local done = Civ6Ai_InGame._TurnStartDone(playerID, turn)
    local now = Civ6Ai_Bridge._WallClock()
    local elapsed = (started ~= nil and now ~= nil) and (now - started) or (ticks / 30)
    if done or elapsed >= Civ6Ai_InGame.TURN_START_WAIT_SECONDS or ticks >= 5000 then
      Civ6Ai_InGame._waitingTurnStart[key] = nil
      Civ6Ai_Util.Log("bridge|local_pulse_after_turn_start|player=" .. tostring(playerID) .. "|turn=" .. tostring(turn)
        .. "|complete=" .. tostring(done) .. "|ticks=" .. tostring(ticks))
      if Game.GetCurrentGameTurn() == turn then
        Civ6Ai_Bridge.RunTurnPulse(playerID)
      end
      return false
    end
    return true
  end)
end

-- Autotest: the local (human) seat pulses from LocalPlayerTurnBegin; other seats
-- wait for TurnStartComplete (queue already applied) then pulse.
function Civ6Ai_Autotest_IsLocalSeat(playerID)
  return Civ6Ai_Config.IsAutotest() and playerID == Game.GetLocalPlayer()
end

function Civ6Ai_OnPlayerTurnStartComplete(playerID)
  if Civ6Ai_Autotest_IsLocalSeat(playerID) then
    return
  end
  Civ6Ai_Bridge.RunTurnPulse(playerID)
end

function Civ6Ai_OnPlayerTurnActivated(playerID, isFirstTime)
  Civ6Ai_SeatExperiment.OnPlayerTurnActivated(playerID)
  if Civ6Ai_Autotest_IsLocalSeat(playerID) then
    return
  end
  if playerID == Game.GetLocalPlayer()
      or (Civ6Ai_Config.ShouldRunBridge ~= nil and Civ6Ai_Config.ShouldRunBridge(playerID)) then
    Civ6Ai_InGame.PulseAfterTurnStart(playerID, Game.GetCurrentGameTurn())
  end
end

function Civ6Ai_OnLoadScreenClose()
  -- STABLE: gates _CanStartAutotestPulse; required before first bridge|pulse.
  Civ6Ai_Bridge.MarkLoadScreenClosed()
  if Civ6Ai_Chat ~= nil and Civ6Ai_Chat.Restore ~= nil then
    Civ6Ai_Chat.Restore()
  end
  if Civ6Ai_Autotest ~= nil and Civ6Ai_Autotest._DisableBoostPopups ~= nil then
    Civ6Ai_Autotest._DisableBoostPopups()
  end
  Civ6Ai_Util.Log("autotest|load_screen_closed")
  if Civ6Ai_Bridge.SameTurnSeats() and Game.GetCurrentGameTurn() <= 1 then
    Civ6Ai_Bridge.PrepulseSeats("host_end")
  end
  -- A loaded save sends LocalPlayerTurnBegin while the load screen is still up,
  -- when the handler above ignores it, so nothing pulsed the current turn and a
  -- reloaded game sat idle. Re-run it now that the screen is closed.
  if Civ6Ai_Config ~= nil and Civ6Ai_Config.IsAutotest() and Game.GetLocalPlayer ~= nil then
    local localId = Game.GetLocalPlayer()
    local localPlayer = localId ~= nil and localId >= 0 and Players[localId] or nil
    if localPlayer ~= nil and localPlayer.IsTurnActive ~= nil and localPlayer:IsTurnActive() then
      Civ6Ai_Util.Log("autotest|load_resume_turn|player=" .. tostring(localId) .. "|turn=" .. tostring(Game.GetCurrentGameTurn()))
      Civ6Ai_OnLocalPlayerTurnBegin()
    end
  end
end

function Civ6Ai_InitializeInGame()
  if Civ6Ai_Config == nil then
    Civ6Ai_Util.Log("ingame|config_missing")
    return
  end
  Civ6Ai_Config.Initialize()
  Civ6Ai_SeatExperiment.Initialize()
  Civ6Ai_Autotest.Initialize()
  Civ6Ai_HostChannel.Initialize()
  Civ6Ai_Chat.Initialize()
  Civ6Ai_Util.InitializeTickPump()
  Civ6Ai_OrderChannel.Initialize()
  ExposedMembers.Civ6Ai = ExposedMembers.Civ6Ai or {}
  ExposedMembers.Civ6Ai.RunTurnPulse = Civ6Ai_Bridge.RunTurnPulse
  ExposedMembers.Civ6Ai.RunChatPulse = Civ6Ai_Bridge.RunChatPulse
  ExposedMembers.Civ6Ai.RequestHostEndTurn = Civ6Ai_Bridge.RequestHostEndTurn
  ExposedMembers.Civ6Ai.HostEndTurnWaiting = Civ6Ai_Bridge.HostEndTurnWaiting
  ExposedMembers.Civ6Ai.HostEndTurnStatus = Civ6Ai_Bridge.HostEndTurnStatus
  if Civ6Ai_MpTest ~= nil then
    Civ6Ai_MpTest.Initialize()
  end
  if not Civ6Ai_InGame._hooks then
    LuaEvents.Civ6Ai_PlayerTurnStartComplete.Add(Civ6Ai_OnPlayerTurnStartComplete)
    Events.PlayerTurnActivated.Add(Civ6Ai_OnPlayerTurnActivated)
    if Events.GameCoreEventPublishComplete ~= nil then
      Events.GameCoreEventPublishComplete.Add(Civ6Ai_InGame._WatchTurnStarts)
    end
    if Events.LocalPlayerTurnBegin ~= nil then
      Events.LocalPlayerTurnBegin.Add(Civ6Ai_OnLocalPlayerTurnBegin)
    end
    if Events.LoadScreenClose ~= nil then
      Events.LoadScreenClose.Add(Civ6Ai_OnLoadScreenClose)
    end
    Civ6Ai_InGame._hooks = true
  end
  Civ6Ai_Util.ProbeIo()
  Civ6Ai_Util.Log("ingame|ready")
  -- A fresh game is still on the load screen at turn 1. A later turn means that
  -- screen already closed; a restarted script must not wait for the event again.
  local turn = Game ~= nil and Game.GetCurrentGameTurn ~= nil and Game.GetCurrentGameTurn() or 0
  if turn > 1 and not Civ6Ai_Bridge.IsLoadScreenClosed() then
    Civ6Ai_Util.Log("autotest|load_screen_already_closed|turn=" .. tostring(turn))
    Civ6Ai_OnLoadScreenClose()
  end
end

Civ6Ai_InitializeInGame()
