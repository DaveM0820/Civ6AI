-- Civ5Ai InGame entry — load modules and register hooks.
Civ5Ai_InGame = Civ5Ai_InGame or {}

print("CIV5AI|ingame|file_loaded")

include("Civ5Ai_Util")
include("Civ5Ai_Paths")
include("Civ5Ai_Config")
include("Civ5Ai_Seats")
include("Civ5Ai_Commands")
include("Civ5Ai_Chat")
include("Civ5Ai_Snapshot")
include("Civ5Ai_Apply")
include("Civ5Ai_Net")
include("Civ5Ai_Diplo")
include("Civ5Ai_Congress")
include("Civ5Ai_Bridge")
include("Civ5Ai_Autotest")

function Civ5Ai_InGame._RegisterExposedMembers()
  ExposedMembers = ExposedMembers or {}
  ExposedMembers.Civ5Ai = ExposedMembers.Civ5Ai or {}
  ExposedMembers.Civ5Ai.ApplyPayload = Civ5Ai_Bridge.ApplyPayload
  ExposedMembers.Civ5Ai.ClearPendingApply = Civ5Ai_Bridge._ClearPendingApplyMod
  ExposedMembers.Civ5Ai.WasAppliedThisPulse = Civ5Ai_Bridge._WasAppliedThisPulse
  ExposedMembers.Civ5Ai.WasPulseFinished = Civ5Ai_Bridge._WasPulseFinished
  ExposedMembers.Civ5Ai.FinishSeat = Civ5Ai_Bridge.FinishSeat
  ExposedMembers.Civ5Ai.EnsureFinishSeat = Civ5Ai_Bridge.EnsureFinishSeat
  ExposedMembers.Civ5Ai.ExpectedApplyTurn = Civ5Ai_Bridge._ExpectedApplyTurn
  ExposedMembers.Civ5Ai.BroadcastPayload = Civ5Ai_Net.BroadcastJson
  ExposedMembers.Civ5Ai.SessionId = Civ5Ai_Bridge.SessionId
  ExposedMembers.Civ5Ai.PumpTicks = Civ5Ai_Util._OnSystemUpdate
  ExposedMembers.Civ5Ai.BindGameCoreUpdateEnd = Civ5Ai_Bridge._BindGameCoreUpdateEnd
  ExposedMembers.Civ5Ai.QueueFinishSeat = Civ5Ai_Bridge._QueueFinishSeat
  ExposedMembers.Civ5Ai.FlushFinishSeatQueue = Civ5Ai_Bridge._FlushFinishSeatQueue
  ExposedMembers.Civ5Ai.OnHumanChat = Civ5Ai_Chat.OnHumanChat
  ExposedMembers.Civ5Ai.TryPendingApply = function()
    if Civ5Ai_HostChannel ~= nil and Civ5Ai_HostChannel.Poll ~= nil then
      Civ5Ai_HostChannel.Poll()
    end
  end
  ExposedMembers.Civ5Ai.ShouldDeferDiploTradeUi = function(playerID)
    return Civ5Ai_Diplo._ShouldDeferTradeUi(playerID)
  end
  ExposedMembers.Civ5Ai.OnDiploTradeDeferred = function(playerID)
    if Civ5Ai_Diplo == nil then
      return
    end
    local pending = Civ5Ai_Diplo.BuildPendingRequests(playerID)
    if #pending > 0 and Civ5Ai_Config.IsSidecarLive() and Civ5Ai_Bridge ~= nil then
      Civ5Ai_Diplo._PulseForPendingDeal(playerID, pending[1].request_id)
    end
  end
  ExposedMembers.Civ5Ai.QueueDiscussionProposal = function(recipientID, senderID, diploUIState, diploData)
    if Civ5Ai_Diplo == nil or Civ5Ai_Diplo.QueueDiscussionProposal == nil then
      return false
    end
    return Civ5Ai_Diplo.QueueDiscussionProposal(recipientID, senderID, diploUIState, diploData)
  end
end
Civ5Ai_InGame._RegisterExposedMembers()

if ContextPtr ~= nil and ContextPtr.LoadNewContext ~= nil then
  ContextPtr:LoadNewContext("Civ5Ai_HostInbox")
end

function Civ5Ai_InGame._SetLabelText(path, text)
  if ContextPtr == nil or ContextPtr.LookUpControl == nil or text == nil then
    return
  end
  local ctrl = ContextPtr:LookUpControl(path)
  if ctrl ~= nil and ctrl.SetText ~= nil then
    ctrl:SetText(text)
  end
end

function Civ5Ai_InGame._RefreshTurnHud()
  if Game == nil then
    return
  end
  local turn = Game.GetGameTurn()
  local turnText = Locale.ConvertTextKey("TXT_KEY_TP_TURN_COUNTER", turn)
  local dateText = ""
  if Game.GetTurnString ~= nil then
    dateText = Game.GetTurnString() or ""
  end
  Civ5Ai_InGame._SetLabelText("/InGame/TopPanel/CurrentTurn", turnText)
  if dateText ~= "" then
    Civ5Ai_InGame._SetLabelText("/InGame/TopPanel/CurrentDate", dateText)
  end
end

function Civ5Ai_OnPlayerDoTurn(playerID)
  if playerID == 0 then
    Civ5Ai_InGame._RefreshTurnHud()
  end
  Civ5Ai_Util.Log(
    "turn|player_do|turn=" .. tostring(Game.GetGameTurn()) .. "|player=" .. tostring(playerID)
  )
  Civ5Ai_Util.Log("diag|player_do|player=" .. tostring(playerID))
  if Civ5Ai_Config ~= nil and Civ5Ai_Config.IsCoActiveMode() and playerID == 0 then
    Civ5Ai_Bridge._OnCoActiveTurnBegin(Game.GetGameTurn())
  end
  -- Enqueue only. Dumps start on ActivePlayerTurnStart after the AI cascade.
  if Civ5Ai_Config.ShouldRunBridge(playerID) then
    Civ5Ai_Bridge.RequestTurnPulse(playerID)
  end
end

function Civ5Ai_OnLoadScreenClose()
  Civ5Ai_Bridge.MarkLoadScreenClosed()
  Civ5Ai_Util.Log("init|load_screen_close")
end

function Civ5Ai_OnDawnShow()
  Civ5Ai_Util.Log("init|dawn_show")
  if Civ5Ai_Autotest ~= nil and Civ5Ai_Autotest._DismissBeginJourney ~= nil then
    Civ5Ai_Autotest._DismissBeginJourney()
  elseif Events.SerialEventDawnOfManHide then
    Events.SerialEventDawnOfManHide()
    Civ5Ai_Util.Log("init|dawn_hidden")
  end
end

function Civ5Ai_InitializeInGame()
  Civ5Ai_Config.Initialize()
  Civ5Ai_Autotest.Initialize()
  Civ5Ai_Net.Initialize()
  Civ5Ai_Util.ProbeIo()
  Civ5Ai_Util.RequireCpOverlay()
  Civ5Ai_Util.InitializeTickPump()
  Civ5Ai_Chat.Initialize()
  Civ5Ai_Diplo.Initialize()
  if Civ5Ai_Congress ~= nil and Civ5Ai_Congress.Initialize ~= nil then
    Civ5Ai_Congress.Initialize()
  end
  Civ5Ai_Apply.Initialize()
  if not Civ5Ai_InGame._hooks then
    if GameEvents and GameEvents.PlayerDoTurn then
      GameEvents.PlayerDoTurn.Add(Civ5Ai_OnPlayerDoTurn)
    else
      Civ5Ai_Util.Log("ingame|player_do_turn_unavailable")
    end
    Events.LoadScreenClose.Add(Civ5Ai_OnLoadScreenClose)
    Events.SerialEventDawnOfManShow.Add(Civ5Ai_OnDawnShow)
    if Civ5Ai_Bridge ~= nil and Civ5Ai_Bridge._BindGameCoreUpdateEnd ~= nil then
      Civ5Ai_Bridge._BindGameCoreUpdateEnd()
    end
    Events.ActivePlayerTurnStart.Add(function()
      Civ5Ai_InGame._RefreshTurnHud()
      Civ5Ai_Util.Log("bridge|kick_after_cascade")
      if Civ5Ai_Config.IsCoActiveMode() then
        Civ5Ai_Bridge._RequestCoActiveManagedTurnPulses()
        Civ5Ai_Bridge._KickPulseQueue()
        return
      end
      local active = Game.GetActivePlayer()
      if Civ5Ai_Config.ShouldRunBridge(active) then
        Civ5Ai_Bridge.RequestTurnPulse(active)
      end
      Civ5Ai_Bridge._KickPulseQueue()
    end)
    Events.SequenceGameInitComplete.Add(function()
      if Civ5Ai_Config.IsAutotest() or Civ5Ai_Config.IsSidecarLive() then
        Civ5Ai_Autotest.OnSequenceComplete()
      end
    end)
    if Civ5Ai_Config.IsAutotest() then
      Events.ActivePlayerTurnStart.Add(function()
        Civ5Ai_Autotest.OnActivePlayerTurnStart()
      end)
    end
    Civ5Ai_InGame._hooks = true
  end
  Civ5Ai_Util.Log("ingame|sequence_complete")
end

Civ5Ai_InitializeInGame()
