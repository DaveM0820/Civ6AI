-- Civ6Ai InGame entry — single Lua context; include modules in dependency order.
Civ6Ai_InGame = Civ6Ai_InGame or {}
include("Civ6Ai_Util.lua")
include("Civ6Ai_Paths.lua")
include("Civ6Ai_Config.lua")
include("Civ6Ai_Snapshot.lua")
include("Civ6Ai_Production.lua")
include("Civ6Ai_Apply.lua")
include("Civ6Ai_MpSync.lua")
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
  Civ6Ai_Util.Log("autotest|local_turn_begin|player=" .. tostring(playerID))
  Civ6Ai_Bridge.RunTurnPulse(playerID)
end

function Civ6Ai_OnPlayerTurnStartComplete(playerID)
  if Civ6Ai_Config.IsAutotest() then
    return
  end
  Civ6Ai_Bridge.RunTurnPulse(playerID)
end

function Civ6Ai_OnPlayerTurnActivated(playerID, isFirstTime)
  Civ6Ai_SeatExperiment.OnPlayerTurnActivated(playerID)
  if Civ6Ai_Config.IsAutotest() then
    return
  end
  Civ6Ai_Bridge.RunTurnPulse(playerID)
end

function Civ6Ai_OnLoadScreenClose()
  -- STABLE: gates _CanStartAutotestPulse; required before first bridge|pulse.
  Civ6Ai_Bridge.MarkLoadScreenClosed()
  if Civ6Ai_Autotest ~= nil and Civ6Ai_Autotest._DisableBoostPopups ~= nil then
    Civ6Ai_Autotest._DisableBoostPopups()
  end
  Civ6Ai_Util.Log("autotest|load_screen_closed")
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
  if Civ6Ai_MpSync ~= nil and Civ6Ai_MpSync.Initialize ~= nil then
    Civ6Ai_MpSync.Initialize()
  end
  Civ6Ai_Util.InitializeTickPump()
  ExposedMembers.Civ6Ai = ExposedMembers.Civ6Ai or {}
  ExposedMembers.Civ6Ai.RunTurnPulse = Civ6Ai_Bridge.RunTurnPulse
  ExposedMembers.Civ6Ai.RunChatPulse = Civ6Ai_Bridge.RunChatPulse
  if not Civ6Ai_InGame._hooks then
    LuaEvents.Civ6Ai_PlayerTurnStartComplete.Add(Civ6Ai_OnPlayerTurnStartComplete)
    Events.PlayerTurnActivated.Add(Civ6Ai_OnPlayerTurnActivated)
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
end

Civ6Ai_InitializeInGame()
