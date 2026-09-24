-- Civ6Ai autotest: auto end-turn, session lifecycle, autotest.log.
Civ6Ai_Autotest = Civ6Ai_Autotest or {}

Civ6Ai_Autotest._stopped = false

function Civ6Ai_Autotest.Initialize()
  if not Civ6Ai_Config.IsAutotest() then
    return
  end
  Civ6Ai_Autotest._EnsureSessionId()
  Civ6Ai_Util.Log("autotest|enabled|stop_turn=" .. tostring(Civ6Ai_Autotest.StopTurn()))
  if Events ~= nil then
    if Events.TechBoostTriggered ~= nil then
      Events.TechBoostTriggered.Add(Civ6Ai_Autotest._OnBoostTriggered)
    end
    if Events.CivicBoostTriggered ~= nil then
      Events.CivicBoostTriggered.Add(Civ6Ai_Autotest._OnBoostTriggered)
    end
    if Events.CityAddedToMap ~= nil then
      Events.CityAddedToMap.Add(Civ6Ai_Autotest._OnCityAddedToMap)
    end
    if Events.LoadScreenClose ~= nil then
      Events.LoadScreenClose.Add(Civ6Ai_Autotest._DisableBoostPopups)
    end
  end
  Civ6Ai_Autotest._DisableBoostPopups()
end

function Civ6Ai_Autotest._AutotestDir()
  local root = Civ6Ai_Config.RootDir()
  if root ~= nil and root ~= "" then
    return Civ6Ai_Util.JoinPath(root, "autotest")
  end
  local logDir = Civ6Ai_Util.LogDir()
  if logDir ~= nil and logDir ~= "" then
    return Civ6Ai_Util.JoinPath(logDir, "civ6ai/autotest")
  end
  return "autotest"
end

function Civ6Ai_Autotest._LogLine(text)
  local path = Civ6Ai_Util.JoinPath(Civ6Ai_Autotest._AutotestDir(), "autotest.log")
  if Civ6Ai_Util.AppendTextLine(path, text) then
    return
  end
  Civ6Ai_Util.Log("autotest|" .. text)
end

function Civ6Ai_Autotest._EnsureSessionId()
  local configured = ""
  if Civ6Ai_Config ~= nil and Civ6Ai_Config.SessionId ~= nil then
    configured = Civ6Ai_Config.SessionId()
  end
  if configured ~= nil and configured ~= "" then
    Civ6Ai_Bridge.SetSessionId(configured)
    Civ6Ai_Util.Log("autotest|session_id=" .. configured)
    Civ6Ai_Autotest._LogLine("session_id=" .. configured)
    return
  end
  local sid = Civ6Ai_Bridge.SessionId()
  if sid == nil or sid == "" or sid == "default" then
    local newId = "autotest"
    if os and os.time then
      newId = "autotest-" .. tostring(os.time())
    end
    Civ6Ai_Bridge.SetSessionId(newId)
    Civ6Ai_Autotest._LogLine("session_id=" .. newId)
  end
end

function Civ6Ai_Autotest.StopTurn()
  if Civ6Ai_Paths and Civ6Ai_Paths.AutotestStopTurn then
    return tonumber(Civ6Ai_Paths.AutotestStopTurn) or 20
  end
  local cfg = GameConfiguration.GetValue("CIV6AI_AUTOTEST_STOP_TURN")
  if cfg ~= nil then
    return tonumber(cfg) or 20
  end
  return 20
end

function Civ6Ai_Autotest.IsStopped()
  return Civ6Ai_Autotest._stopped
end

function Civ6Ai_Autotest.AfterPulse(playerID)
  if not Civ6Ai_Config.IsAutotest() then
    return
  end
  if Civ6Ai_Autotest._stopped then
    return
  end
  local turn = Game.GetCurrentGameTurn()
  Civ6Ai_Autotest._LogLine("pulse|turn=" .. tostring(turn) .. "|player=" .. tostring(playerID))
  Civ6Ai_Autotest._DisableBoostPopups()
  Civ6Ai_Autotest._CloseQueuedPopups()
  Civ6Ai_Autotest._DismissBlockers(playerID)
  Civ6Ai_Autotest._EndManagedTurn(playerID)
  if turn >= Civ6Ai_Autotest.StopTurn() then
    Civ6Ai_Autotest._WriteSessionSummary()
    Civ6Ai_Autotest._stopped = true
    Civ6Ai_Autotest._LogLine("stop|turn=" .. tostring(turn))
  end
end

function Civ6Ai_Autotest._DisableBoostPopups()
  if LuaEvents ~= nil and LuaEvents.TutorialUIRoot_DisableTechAndCivicPopups ~= nil then
    LuaEvents.TutorialUIRoot_DisableTechAndCivicPopups()
  end
end

function Civ6Ai_Autotest._CloseQueuedPopups()
  if ContextPtr == nil or UIManager == nil or UIManager.DequeuePopup == nil then
    return
  end
  local names = {
    "BoostUnlockedPopup",
    "TechCivicCompletedPopup",
    "CityNamePopup",
    "ChooseCityNamePopup",
    "CityRenamePopup",
    "InGamePopup",
    "GenericPopup",
    "PopupDialog",
  }
  local closed = 0
  for _, name in ipairs(names) do
    local control = ContextPtr:LookUpControl("/InGame/" .. name)
    if control ~= nil then
      local hidden = true
      if control.IsHidden ~= nil then
        hidden = control:IsHidden()
      end
      if not hidden then
        pcall(function() UIManager:DequeuePopup(control) end)
        closed = closed + 1
      end
    end
  end
  if LuaEvents ~= nil and LuaEvents.TechCivicCompletedPopup_Closed ~= nil then
    pcall(function() LuaEvents.TechCivicCompletedPopup_Closed() end)
  end
  if closed > 0 then
    Civ6Ai_Autotest._LogLine("popups_closed|count=" .. tostring(closed))
    Civ6Ai_Util.Log("autotest|popups_closed|count=" .. tostring(closed))
  end
end

function Civ6Ai_Autotest._OnBoostTriggered()
  if not Civ6Ai_Config.IsAutotest() then
    return
  end
  Civ6Ai_Autotest._DisableBoostPopups()
  Civ6Ai_Util.ScheduleTick(function()
    Civ6Ai_Autotest._CloseQueuedPopups()
    return false
  end)
end

function Civ6Ai_Autotest._DismissCityNamePopups()
  if ContextPtr == nil then
    return 0
  end
  local names = {
    "CityNamePopup",
    "ChooseCityNamePopup",
    "CityRenamePopup",
    "NewCityPopup",
    "PopupDialog",
    "GenericPopup",
  }
  local prefixes = {
    "/InGame/",
    "/InGame/Popups/",
    "/InGame/WorldView/",
  }
  local closed = 0
  for _, prefix in ipairs(prefixes) do
    for _, name in ipairs(names) do
      local control = ContextPtr:LookUpControl(prefix .. name)
      if control ~= nil then
        local hidden = true
        if control.IsHidden ~= nil then
          hidden = control:IsHidden()
        end
        if not hidden then
          if UIManager ~= nil and UIManager.DequeuePopup ~= nil then
            pcall(function() UIManager:DequeuePopup(control) end)
          end
          if control.SetHide ~= nil then
            pcall(function() control:SetHide(true) end)
          end
          closed = closed + 1
        end
      end
    end
  end
  if closed > 0 then
    Civ6Ai_Autotest._LogLine("city_name_popups_closed|count=" .. tostring(closed))
    Civ6Ai_Util.Log("autotest|city_name_popups_closed|count=" .. tostring(closed))
  end
  return closed
end

function Civ6Ai_Autotest._OnCityAddedToMap(playerID, cityID, x, y)
  if not Civ6Ai_Config.IsAutotest() then
    return
  end
  Civ6Ai_Autotest._OnBoostTriggered()
  Civ6Ai_Util.ScheduleTick(function()
    Civ6Ai_Autotest._DismissCityNamePopups()
    Civ6Ai_Autotest._CloseQueuedPopups()
    Civ6Ai_Autotest._NudgeEnter(playerID or Game.GetLocalPlayer())
    return false
  end)
end

function Civ6Ai_Autotest._DismissBlockers(playerID)
  local list = NotificationManager.GetList(playerID)
  if list == nil then
    return
  end
  local count = 0
  for _, nid in ipairs(list) do
    local entry = NotificationManager.Find(playerID, nid)
    if entry ~= nil and not entry:IsDismissed() then
      local blocking = entry:GetEndTurnBlocking()
      if blocking ~= nil and blocking ~= 0 then
        pcall(function() NotificationManager.SendActivated(playerID, nid) end)
        pcall(function() NotificationManager.Dismiss(playerID, nid) end)
        count = count + 1
      end
    end
  end
  if count > 0 then
    Civ6Ai_Autotest._LogLine("blockers|player=" .. tostring(playerID) .. "|count=" .. tostring(count))
  end
end

function Civ6Ai_Autotest._SkipUnitMoves(playerID)
  pcall(function()
    local player = Players[playerID]
    if player == nil then
      return
    end
    local units = player:GetUnits()
    if units == nil then
      return
    end
    if units.Members ~= nil then
      for _, unit in units:Members() do
        if unit:GetX() ~= -9999 and unit:GetMovesRemaining() > 0
            and not Civ6Ai_Apply._UnitWasOrdered(playerID, unit) then
          UnitManager.FinishMoves(unit)
        end
      end
    else
      for i = 0, units:GetCount() - 1 do
        local unit = units:Get(i)
        if unit ~= nil and unit:GetX() ~= -9999 and unit:GetMovesRemaining() > 0
            and not Civ6Ai_Apply._UnitWasOrdered(playerID, unit) then
          UnitManager.FinishMoves(unit)
        end
      end
    end
  end)
end

function Civ6Ai_Autotest._RequestEndTurn()
  if UI == nil or UI.RequestAction == nil then
    return false, "no_ui_request_action"
  end
  local action = nil
  if ActionTypes ~= nil and ActionTypes.ACTION_ENDTURN ~= nil then
    action = ActionTypes.ACTION_ENDTURN
  elseif GameInfo ~= nil and GameInfo.Types ~= nil and GameInfo.Types.ACTION_ENDTURN ~= nil then
    action = GameInfo.Types.ACTION_ENDTURN.Hash
  end
  if action == nil then
    return false, "no_end_turn_action"
  end
  UI.RequestAction(action)
  return true, ""
end

function Civ6Ai_Autotest._NudgeEnter(playerID)
  local text = "nudge_enter|player=" .. tostring(playerID)
  Civ6Ai_Util.Log("autotest|" .. text)
  Civ6Ai_Autotest._LogLine(text)
end

function Civ6Ai_Autotest._TryEndTurnNow(playerID)
  for attempt = 1, 6 do
    if UI.CanEndTurn ~= nil and UI.CanEndTurn() then
      break
    end
    Civ6Ai_Apply.ResolveAllUnitOrders(playerID)
    Civ6Ai_Autotest._CloseQueuedPopups()
    Civ6Ai_Autotest._DismissBlockers(playerID)
  end
  if UI.CanEndTurn ~= nil and not UI.CanEndTurn() then
    Civ6Ai_Apply.ResolveAllUnitOrders(playerID)
    Civ6Ai_Autotest._CloseQueuedPopups()
    Civ6Ai_Autotest._DismissBlockers(playerID)
    return false, "end_turn_blocked"
  end
  local endOk, endReason = Civ6Ai_Autotest._RequestEndTurn()
  if not endOk then
    return false, endReason
  end
  return true, ""
end

function Civ6Ai_Autotest._ScheduleEndTurnRetry(playerID, origPlayer, maxAttempts)
  local attempts = 0
  Civ6Ai_Autotest._NudgeEnter(playerID)
  Civ6Ai_Util.ScheduleTick(function()
    attempts = attempts + 1
    Civ6Ai_Autotest._CloseQueuedPopups()
    Civ6Ai_Autotest._DismissBlockers(playerID)
    Civ6Ai_Apply.ResolveAllUnitOrders(playerID)
    if UI.CanEndTurn ~= nil and UI.CanEndTurn() then
      local endOk, endReason = Civ6Ai_Autotest._RequestEndTurn()
      pcall(function()
        if origPlayer ~= nil and PlayerManager ~= nil and PlayerManager.SetLocalPlayerAndObserver ~= nil then
          PlayerManager.SetLocalPlayerAndObserver(origPlayer)
        end
      end)
      if endOk then
        Civ6Ai_Autotest._LogLine("end_turn|player=" .. tostring(playerID))
      else
        Civ6Ai_Autotest._LogLine("end_turn_failed|player=" .. tostring(playerID) .. "|" .. tostring(endReason))
      end
      return false
    end
    if attempts == 1 or attempts % 3 == 0 then
      Civ6Ai_Autotest._NudgeEnter(playerID)
    end
    if attempts >= maxAttempts then
      pcall(function()
        if origPlayer ~= nil and PlayerManager ~= nil and PlayerManager.SetLocalPlayerAndObserver ~= nil then
          PlayerManager.SetLocalPlayerAndObserver(origPlayer)
        end
      end)
      Civ6Ai_Autotest._LogLine("end_turn_failed|player=" .. tostring(playerID) .. "|blocked_after_nudge")
      return false
    end
    return true
  end)
end

function Civ6Ai_Autotest._SchedulePopupDrain(playerID)
  if Civ6Ai_Autotest._draining then
    return
  end
  Civ6Ai_Autotest._draining = true
  local attempts = 0
  local startTurn = Game.GetCurrentGameTurn()
  Civ6Ai_Util.ScheduleTick(function()
    attempts = attempts + 1
    Civ6Ai_Autotest._CloseQueuedPopups()
    Civ6Ai_Autotest._DismissBlockers(playerID)
    if Game.GetCurrentGameTurn() ~= startTurn then
      Civ6Ai_Autotest._draining = false
      return false
    end
    if UI.CanEndTurn ~= nil and UI.CanEndTurn() then
      Civ6Ai_Autotest._RequestEndTurn()
    elseif attempts == 1 or attempts % 3 == 0 then
      Civ6Ai_Autotest._NudgeEnter(playerID)
    end
    if attempts >= 16 then
      Civ6Ai_Autotest._draining = false
      Civ6Ai_Autotest._NudgeEnter(playerID)
      return false
    end
    return true
  end)
end

function Civ6Ai_Autotest._EndManagedTurn(playerID)
  Civ6Ai_Autotest._CloseQueuedPopups()
  Civ6Ai_Autotest._DismissBlockers(playerID)
  Civ6Ai_Apply.ResolveAllUnitOrders(playerID)
  local origPlayer = Game.GetLocalPlayer()
  if PlayerManager == nil or PlayerManager.SetLocalPlayerAndObserver == nil then
    if Game.GetLocalPlayer() == playerID then
      local endOk, endReason = Civ6Ai_Autotest._TryEndTurnNow(playerID)
      if endOk then
        Civ6Ai_Autotest._LogLine("end_turn|player=" .. tostring(playerID))
        Civ6Ai_Autotest._SchedulePopupDrain(playerID)
      else
        Civ6Ai_Autotest._NudgeEnter(playerID)
        Civ6Ai_Autotest._LogLine("end_turn_failed|player=" .. tostring(playerID) .. "|" .. tostring(endReason))
        Civ6Ai_Autotest._SchedulePopupDrain(playerID)
      end
    else
      Civ6Ai_Autotest._LogLine("end_turn_skipped|player=" .. tostring(playerID) .. "|no_player_manager")
    end
    return
  end
  local ok, err = pcall(function()
    PlayerManager.SetLocalPlayerAndObserver(playerID)
    local endOk, endReason = Civ6Ai_Autotest._TryEndTurnNow(playerID)
    if endOk then
      return
    end
    Civ6Ai_Autotest._ScheduleEndTurnRetry(playerID, origPlayer, 12)
    error("end_turn_pending_nudge")
  end)
  if ok then
    pcall(function()
      if origPlayer ~= nil then
        PlayerManager.SetLocalPlayerAndObserver(origPlayer)
      end
    end)
    Civ6Ai_Autotest._LogLine("end_turn|player=" .. tostring(playerID))
    Civ6Ai_Autotest._SchedulePopupDrain(playerID)
  elseif err == "end_turn_pending_nudge" then
    Civ6Ai_Autotest._LogLine("end_turn_blocked|player=" .. tostring(playerID))
  else
    pcall(function()
      if origPlayer ~= nil then
        PlayerManager.SetLocalPlayerAndObserver(origPlayer)
      end
    end)
    Civ6Ai_Autotest._LogLine("end_turn_failed|player=" .. tostring(playerID) .. "|" .. tostring(err))
  end
end

function Civ6Ai_Autotest._WriteSessionSummary()
  local root = Civ6Ai_Config.RootDir()
  local sessionId = Civ6Ai_Bridge.SessionId()
  local summary = {
    event = "session_summary",
    session_id = sessionId,
    stop_turn = Civ6Ai_Autotest.StopTurn(),
    final_turn = Game.GetCurrentGameTurn(),
    stopped = true,
  }
  local path = Civ6Ai_Util.JoinPath(Civ6Ai_Autotest._AutotestDir(), "session_summary.json")
  Civ6Ai_Util.WriteTextFile(path, Civ6Ai_Util.EncodeJsonObject(summary) .. "\n")
  Civ6Ai_Autotest._LogLine("session_summary_written")
end
