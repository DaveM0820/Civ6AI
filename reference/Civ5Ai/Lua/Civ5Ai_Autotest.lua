-- Civ5Ai autotest: autoplay, blocker dismiss, session lifecycle.
Civ5Ai_Autotest = Civ5Ai_Autotest or {}

Civ5Ai_Autotest._stopped = false
Civ5Ai_Autotest._autoplayArmed = false
Civ5Ai_Autotest._beginJourneyDismissed = false

function Civ5Ai_Autotest.Initialize()
  if Civ5Ai_Config.IsAutotest() then
    Civ5Ai_Autotest._EnsureSessionId()
    Civ5Ai_Util.Log("autotest|enabled|stop_turn=" .. tostring(Civ5Ai_Autotest.StopTurn()))
  end
  if Civ5Ai_Config.IsAutotest() or Civ5Ai_Config.IsSidecarLive() then
    Civ5Ai_Autotest._ArmLeaderDismiss()
    Civ5Ai_Autotest._ArmUiDismissPump()
  end
end

function Civ5Ai_Autotest._OnLeaderHeadShown()
  local active = Game.GetActivePlayer()
  if Civ5Ai_Diplo ~= nil then
    if Civ5Ai_Diplo._PumpTradeUiDismiss ~= nil then
      Civ5Ai_Diplo._PumpTradeUiDismiss(active)
    elseif Civ5Ai_Diplo.HandleLeaderTradeBlocker ~= nil then
      Civ5Ai_Diplo.HandleLeaderTradeBlocker(active)
    end
  end
  Civ5Ai_Autotest._ReleaseUiFocus()
end

function Civ5Ai_Autotest._ArmLeaderDismiss()
  if Civ5Ai_Autotest._leaderDismissArmed then
    return
  end
  Civ5Ai_Autotest._leaderDismissArmed = true
  if Events ~= nil and Events.AILeaderMessage ~= nil then
    Events.AILeaderMessage.Add(function()
      Civ5Ai_Util.Log("autotest|leader_message")
      Civ5Ai_Autotest._OnLeaderHeadShown()
    end)
  end
  -- HostInbox SetUpdate does not run while LeaderHead has focus, so a
  -- scheduled tick never hits Goodbye. EUI fires this from OnShowHide.
  if LuaEvents ~= nil then
    LuaEvents.EUILeaderHeadRoot.Add(function()
      Civ5Ai_Util.Log("autotest|leader_shown")
      Civ5Ai_Autotest._OnLeaderHeadShown()
    end)
  end
end

function Civ5Ai_Autotest._ArmUiDismissPump()
  if Civ5Ai_Autotest._uiDismissArmed then
    return
  end
  Civ5Ai_Autotest._uiDismissArmed = true
  Civ5Ai_Util.ScheduleTick(function()
    if Civ5Ai_Autotest._stopped then
      return false
    end
    local active = Game.GetActivePlayer()
    if Civ5Ai_Seats == nil or not Civ5Ai_Seats.IsLlmHuman(active) then
      return true
    end
    local held, uiReason = Civ5Ai_Autotest._UiHoldsEndTurn()
    if held then
      if uiReason == "leader"
        or uiReason == "/LeaderHeadRoot/DiploTrade"
        or uiReason == "/LeaderHeadRoot/DiscussionDialog"
        or uiReason == "/InGame/DiploCorner/SimpleDiplo"
        or uiReason == "/InGame/WorldView/SimpleDiploTrade" then
        Civ5Ai_Autotest._OnLeaderHeadShown()
      else
        Civ5Ai_Autotest._ReleaseUiFocus()
      end
    end
    return true
  end)
end

function Civ5Ai_Autotest._EnsureSessionId()
  local configured = Civ5Ai_Config.SessionId()
  if configured ~= nil and configured ~= "" then
    Civ5Ai_Bridge.SetSessionId(configured)
    Civ5Ai_Util.Log("autotest|session_id=" .. configured)
    return
  end
  local sid = Civ5Ai_Bridge.SessionId()
  if sid == nil or sid == "" or sid == "default" then
    local newId = "autotest"
    if os and os.time then
      newId = "autotest-" .. tostring(os.time())
    end
    Civ5Ai_Bridge.SetSessionId(newId)
    Civ5Ai_Util.Log("autotest|session_id=" .. newId)
  end
end

function Civ5Ai_Autotest.StopTurn()
  return Civ5Ai_Config.AutotestStopTurn()
end

function Civ5Ai_Autotest.HasTurnCap()
  local stop = Civ5Ai_Autotest.StopTurn()
  return type(stop) == "number" and stop > 0
end

function Civ5Ai_Autotest.ReachedStopTurn(turn)
  return Civ5Ai_Autotest.HasTurnCap() and turn >= Civ5Ai_Autotest.StopTurn()
end

function Civ5Ai_Autotest.IsStopped()
  return Civ5Ai_Autotest._stopped
end

function Civ5Ai_Autotest._ArmAutoplay()
  if Civ5Ai_Autotest._autoplayArmed then
    return
  end
  Game.SetPausePlayer(-1)
  if Civ5Ai_Config.IsSidecarLive() then
    -- Continuous autoplay races ahead of inbox apply + LLM. End turn via nudge
    -- after each seat's apply completes (see RequestEndTurnNudge).
    Civ5Ai_Autotest._autoplayArmed = true
    Civ5Ai_Util.Log("autotest|autoplay_deferred|sidecar_live")
    return
  end
  local n = 99999
  if Civ5Ai_Autotest.HasTurnCap() then
    n = Civ5Ai_Autotest.StopTurn() + 2
  end
  Game.SetAIAutoPlay(n)
  Civ5Ai_Autotest._autoplayArmed = true
  Civ5Ai_Util.Log("autotest|autoplay_armed|n=" .. tostring(n))
end

function Civ5Ai_Autotest._ReleaseUiFocus()
  local host = ExposedMembers ~= nil and ExposedMembers.Civ5Ai or nil
  if host ~= nil and host.ReleaseUiFocus ~= nil then
    host.ReleaseUiFocus()
  end
  if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._DismissBlockingPopups ~= nil then
    Civ5Ai_Apply._DismissBlockingPopups()
  end
  if UI ~= nil and UI.IsCityScreenUp ~= nil and UI.IsCityScreenUp() then
    if UI.SetCityScreenUp ~= nil then
      UI.SetCityScreenUp(false)
    end
  end
  if Events ~= nil and Events.SerialEventExitCityScreen ~= nil then
    Events.SerialEventExitCityScreen()
  end
  if UI ~= nil and UI.ClearSelectedCities ~= nil then
    UI.ClearSelectedCities()
  end
  if UI ~= nil and UI.SetInterfaceMode ~= nil and InterfaceModeTypes ~= nil then
    UI.SetInterfaceMode(InterfaceModeTypes.INTERFACEMODE_SELECTION)
  end
  -- ChatEntry focus (Tab) makes CONTROL_ENDTURN a no-op with blocking -1.
  if ContextPtr ~= nil and ContextPtr.LookUpControl ~= nil then
    local chat = ContextPtr:LookUpControl("/InGame/DiploCorner/ChatEntry")
    if chat == nil then
      chat = ContextPtr:LookUpControl("/InGame/WorldView/DiploCorner/ChatEntry")
    end
    if chat ~= nil and chat.ClearFocus ~= nil then
      chat:ClearFocus()
    end
  end
end

function Civ5Ai_Autotest._EndTurnBlocking()
  local player = Players[Game.GetActivePlayer()]
  if player == nil or player.GetEndTurnBlockingType == nil then
    return nil
  end
  return player:GetEndTurnBlockingType()
end

function Civ5Ai_Autotest._EndTurnBlockingFor(playerID)
  local player = Players[playerID]
  if player == nil or player.GetEndTurnBlockingType == nil then
    return nil
  end
  return player:GetEndTurnBlockingType()
end

function Civ5Ai_Autotest._NoEndTurnBlockingFor(playerID)
  return Civ5Ai_Autotest._NoEndTurnBlocking(Civ5Ai_Autotest._EndTurnBlockingFor(playerID))
end

function Civ5Ai_Autotest._UnitsStillBlockingFor(playerID)
  return Civ5Ai_Autotest._UnitsStillBlocking(Civ5Ai_Autotest._EndTurnBlockingFor(playerID))
end

function Civ5Ai_Autotest._UnitsStillBlocking(blocking)
  local t = EndTurnBlockingTypes
  if t == nil then
    return false
  end
  return blocking == t.ENDTURN_BLOCKING_UNITS
    or blocking == t.ENDTURN_BLOCKING_STACKED_UNITS
    or blocking == t.ENDTURN_BLOCKING_UNIT_NEEDS_ORDERS
end

function Civ5Ai_Autotest._NoEndTurnBlocking(blocking)
  local t = EndTurnBlockingTypes
  if blocking == nil or blocking == -1 then
    return true
  end
  if t ~= nil and blocking == t.NO_ENDTURN_BLOCKING_TYPE then
    return true
  end
  return false
end

function Civ5Ai_Autotest._ResolveEndTurnBlocking(playerID, blocking)
  if Civ5Ai_Apply ~= nil and Civ5Ai_Apply.ResolveEndTurnBlocking ~= nil then
    Civ5Ai_Apply.ResolveEndTurnBlocking(playerID, blocking)
  end
end

function Civ5Ai_Autotest._OtherSeatTurnActive(selfPlayer)
  local last = 21
  if GameDefines ~= nil and GameDefines.MAX_MAJOR_CIVS ~= nil then
    last = GameDefines.MAX_MAJOR_CIVS - 1
  end
  for i = 0, last do
    if i ~= selfPlayer then
      local p = Players[i]
      if p ~= nil and p.IsAlive ~= nil and p:IsAlive() and p.IsTurnActive ~= nil and p:IsTurnActive() then
        return true
      end
    end
  end
  return false
end

function Civ5Ai_Autotest._SeatTurnFinished(playerID, startTurn)
  if Game.GetGameTurn() ~= startTurn then
    return true
  end
  local player = Players[playerID]
  if player ~= nil and player.IsTurnActive ~= nil and not player:IsTurnActive() then
    return true
  end
  return false
end

function Civ5Ai_Autotest._PopupOpen(path)
  if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._ControlVisible ~= nil then
    return Civ5Ai_Apply._ControlVisible(path)
  end
  if ContextPtr == nil or ContextPtr.LookUpControl == nil then
    return false
  end
  local ctx = ContextPtr:LookUpControl(path)
  return ctx ~= nil and ctx.IsHidden ~= nil and not ctx:IsHidden()
end

function Civ5Ai_Autotest._UiHoldsEndTurn()
  if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._LeaderHeadShowing ~= nil and Civ5Ai_Apply._LeaderHeadShowing() then
    return true, "leader"
  end
  local paths = {
    "/InGame/GoodyHutPopup",
    "/InGame/GenericPopup",
    "/InGame/ResearchChooserPopup",
    "/InGame/ChooseTechPopup",
    "/InGame/TechPopup",
    "/InGame/TechAwardPopup",
    "/InGame/ProductionPopup",
    "/InGame/ChooseProductionPopup",
    "/InGame/SocialPolicyPopup",
    "/InGame/ChoosePantheonPopup",
    "/InGame/ChooseReligionPopup",
    "/LeaderHeadRoot",
    "/LeaderHeadRoot/DiploTrade",
    "/LeaderHeadRoot/DiscussionDialog",
    "/InGame/LeaderHeadRoot",
    "/InGame/DiploCorner/SimpleDiplo",
    "/InGame/WorldView/SimpleDiploTrade",
  }
  for _, path in ipairs(paths) do
    if Civ5Ai_Autotest._PopupOpen(path) then
      return true, path
    end
  end
  return false, nil
end

function Civ5Ai_Autotest._PressEndTurnButton(playerID)
  -- ActionInfoPanel: HostInbox Game.DoControl is ignored. Prefer ExposedMembers
  -- PanelPressEndTurn (panel Lua + GameCoreUpdateEnd drain; works minimized).
  -- Fallback LuaEvents.Civ5AiPressEndTurn. Never mouse / SendInput.
  if ExposedMembers ~= nil
    and ExposedMembers.Civ5Ai ~= nil
    and ExposedMembers.Civ5Ai.PanelPressEndTurn ~= nil
  then
    ExposedMembers.Civ5Ai.PanelPressEndTurn()
    Civ5Ai_Util.Log(
      "autotest|press_end_turn_button|player="
        .. tostring(playerID)
        .. "|via=exposed"
    )
    return true
  end
  if LuaEvents ~= nil then
    LuaEvents.Civ5AiPressEndTurn()
    Civ5Ai_Util.Log(
      "autotest|press_end_turn_button|player="
        .. tostring(playerID)
        .. "|via=event"
    )
    return true
  end
  return false
end

function Civ5Ai_Autotest._RequestEndTurn(seatPlayerID)
  if Game == nil or GameInfoTypes == nil or Game.DoControl == nil then
    return false, "no_end_turn_control"
  end
  if Game.SetPausePlayer ~= nil then
    Game.SetPausePlayer(-1)
  end
  local active = Game.GetActivePlayer()
  local playerID = seatPlayerID
  if playerID == nil then
    playerID = active
  end
  if playerID ~= active then
    return false, "end_turn_wrong_active|seat=" .. tostring(playerID) .. "|active=" .. tostring(active)
  end
  -- Rapidly clear city screen / chat / production / research before CanDoControl.
  -- DoControl is a no-op while CanDoControl is false; hammering it keeps busy.
  if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._ClearLocalHumanEndTurnBlockers ~= nil then
    Civ5Ai_Apply._ClearLocalHumanEndTurnBlockers(playerID, true)
  else
    Civ5Ai_Autotest._ReleaseUiFocus()
  end
  local blocking = Civ5Ai_Autotest._EndTurnBlocking()
  -- CP asserts on sendTurnComplete while UNITS still block. Skip idle leftovers
  -- before giving up; in-flight missions stay protected inside SkipUnorderedUnits.
  if Civ5Ai_Autotest._UnitsStillBlocking(blocking) then
    if Civ5Ai_Apply ~= nil and Civ5Ai_Apply.SkipUnorderedUnits ~= nil then
      Civ5Ai_Apply.SkipUnorderedUnits(playerID)
      if Civ5Ai_Apply._FinishAllUnitsWithMoves ~= nil then
        Civ5Ai_Apply._FinishAllUnitsWithMoves(playerID, true)
      end
      if Civ5Ai_Apply._ClearLocalHumanEndTurnUi ~= nil then
        Civ5Ai_Apply._ClearLocalHumanEndTurnUi(playerID)
      end
    end
    blocking = Civ5Ai_Autotest._EndTurnBlocking()
  end
  -- After SkipUnordered/_FinishAllUnitsWithMoves, also skip idle leftovers for
  -- local-human engine UNITS blocks (UiApply/net SKIP inside _FinishUnitMoves).
  if Civ5Ai_Autotest._UnitsStillBlocking(blocking)
      and Civ5Ai_Apply ~= nil
      and Civ5Ai_Apply._SkipIdleUnitsForEngineBlock ~= nil then
    Civ5Ai_Apply._SkipIdleUnitsForEngineBlock(playerID)
    if Civ5Ai_Apply._ClearLocalHumanEndTurnUi ~= nil then
      Civ5Ai_Apply._ClearLocalHumanEndTurnUi(playerID)
    end
    blocking = Civ5Ai_Autotest._EndTurnBlocking()
  end
  if Civ5Ai_Autotest._UnitsStillBlocking(blocking) then
    -- Phantom UNITS block: every unit moves=0 / not ready / not busy, but
    -- GetEndTurnBlockingType stays UNITS (live t43 auto act=6/0). After skip
    -- idle + zero-auto, allow the do_anyway CONTROL_ENDTURN path.
    local phantom = Civ5Ai_Apply ~= nil
      and Civ5Ai_Apply._AllUnitsLookFinishedForEndTurn ~= nil
      and Civ5Ai_Apply._AllUnitsLookFinishedForEndTurn(playerID) == true
    if phantom then
      if Civ5Ai_Apply._ZeroAutomatedMovesForEndTurn ~= nil then
        Civ5Ai_Apply._ZeroAutomatedMovesForEndTurn(playerID)
      end
      if Civ5Ai_Apply._AcknowledgePhantomUnitsBlocking ~= nil then
        Civ5Ai_Apply._AcknowledgePhantomUnitsBlocking(playerID)
        blocking = Civ5Ai_Autotest._EndTurnBlocking()
      end
      if Civ5Ai_Apply._ClearLocalHumanEndTurnUi ~= nil then
        Civ5Ai_Apply._ClearLocalHumanEndTurnUi(playerID)
      end
      if Civ5Ai_Autotest._NoEndTurnBlocking(blocking) then
        Civ5Ai_Util.Log(
          "autotest|CONTROL_ENDTURN|blocking="
            .. tostring(blocking)
            .. "|phantom_units_acked"
        )
      else
        Civ5Ai_Util.Log(
          "autotest|CONTROL_ENDTURN|blocking="
            .. tostring(blocking)
            .. "|phantom_units_clear|try_anyway"
        )
      end
      -- Fall through to DoControl / press; do not return end_turn_blocked.
    else
      Civ5Ai_Autotest._ReleaseUiFocus()
      return false, "end_turn_blocked|" .. tostring(blocking)
    end
  end
  -- CP asserts on sendTurnComplete while production/research/etc. still block.
  if not Civ5Ai_Autotest._NoEndTurnBlocking(blocking) then
    local unitsPhantom = Civ5Ai_Autotest._UnitsStillBlocking(blocking)
      and Civ5Ai_Apply ~= nil
      and Civ5Ai_Apply._AllUnitsLookFinishedForEndTurn ~= nil
      and Civ5Ai_Apply._AllUnitsLookFinishedForEndTurn(playerID) == true
    if not unitsPhantom then
      Civ5Ai_Autotest._ResolveEndTurnBlocking(playerID, blocking)
      blocking = Civ5Ai_Autotest._EndTurnBlocking()
      local t = EndTurnBlockingTypes
      if not Civ5Ai_Autotest._NoEndTurnBlocking(blocking)
          and t ~= nil
          and blocking == t.ENDTURN_BLOCKING_PRODUCTION
          and Civ5Ai_Apply ~= nil
          and Civ5Ai_Apply._AllCitiesHaveProductionQueued ~= nil
          and Civ5Ai_Apply._AllCitiesHaveProductionQueued(playerID) then
        if Civ5Ai_Apply._ResyncLocalHumanProduction ~= nil then
          Civ5Ai_Apply._ResyncLocalHumanProduction(playerID)
        end
        if Civ5Ai_Apply._AcknowledgeProductionBlocking ~= nil then
          Civ5Ai_Apply._AcknowledgeProductionBlocking(playerID)
        end
        -- DLL clearer also drops phantom PRODUCTION once rebuilt; safe no-op today.
        if Game ~= nil and Game.Civ5AiClearUnitsEndTurnBlock ~= nil then
          Game.Civ5AiClearUnitsEndTurnBlock(playerID)
        end
        blocking = Civ5Ai_Autotest._EndTurnBlocking()
        if Civ5Ai_Autotest._NoEndTurnBlocking(blocking) then
          Civ5Ai_Util.Log(
            "autotest|CONTROL_ENDTURN|blocking="
              .. tostring(blocking)
              .. "|phantom_production_acked"
          )
        end
      end
      if not Civ5Ai_Autotest._NoEndTurnBlocking(blocking) then
        local stillPhantom = Civ5Ai_Autotest._UnitsStillBlocking(blocking)
          and Civ5Ai_Apply ~= nil
          and Civ5Ai_Apply._AllUnitsLookFinishedForEndTurn ~= nil
          and Civ5Ai_Apply._AllUnitsLookFinishedForEndTurn(playerID) == true
        if not stillPhantom then
          Civ5Ai_Autotest._ReleaseUiFocus()
          return false, "end_turn_blocked|" .. tostring(blocking)
        end
      end
    end
  end
  local uiHeld, uiReason = Civ5Ai_Autotest._UiHoldsEndTurn()
  if uiHeld then
    if uiReason == "/InGame/ChoosePantheonPopup"
      or uiReason == "/InGame/ChooseReligionPopup" then
      if Civ5Ai_Apply ~= nil and Civ5Ai_Apply.ResolveFaithBlockers ~= nil then
        Civ5Ai_Apply.ResolveFaithBlockers(playerID)
      end
    elseif uiReason == "leader" then
      Civ5Ai_Autotest._OnLeaderHeadShown()
      return false, "end_turn_ui|" .. tostring(uiReason)
    end
    Civ5Ai_Autotest._ReleaseUiFocus()
    return false, "end_turn_ui|" .. tostring(uiReason)
  end
  -- CONTROL_ENDTURN while other managed seats are still turn-active is
  -- what trips CP's numActive == getNumGameTurnActive assert.
  if Civ5Ai_Autotest._OtherSeatTurnActive(playerID) then
    Civ5Ai_Autotest._ReleaseUiFocus()
    return false, "end_turn_waiting_peers"
  end
  local control = GameInfoTypes.CONTROL_ENDTURN
  local blockingNow = Civ5Ai_Autotest._EndTurnBlocking()
  local phantomNow = Civ5Ai_Autotest._UnitsStillBlocking(blockingNow)
    and Civ5Ai_Apply ~= nil
    and Civ5Ai_Apply._AllUnitsLookFinishedForEndTurn ~= nil
    and Civ5Ai_Apply._AllUnitsLookFinishedForEndTurn(playerID) == true
  if Civ5Ai_Autotest._UnitsStillBlocking(blockingNow)
      and Civ5Ai_Apply ~= nil
      and Civ5Ai_Apply._EndTurnsForReadyUnits ~= nil then
    Civ5Ai_Apply._EndTurnsForReadyUnits(playerID)
    blockingNow = Civ5Ai_Autotest._EndTurnBlocking()
  end
  phantomNow = Civ5Ai_Autotest._UnitsStillBlocking(blockingNow)
    and Civ5Ai_Apply ~= nil
    and Civ5Ai_Apply._AllUnitsLookFinishedForEndTurn ~= nil
    and Civ5Ai_Apply._AllUnitsLookFinishedForEndTurn(playerID) == true
  if phantomNow then
    if Civ5Ai_Apply._AcknowledgePhantomUnitsBlocking ~= nil then
      Civ5Ai_Apply._AcknowledgePhantomUnitsBlocking(playerID)
      blockingNow = Civ5Ai_Autotest._EndTurnBlocking()
    end
    -- Give net SKIP from EndTurnsForReadyUnits a tick to apply before forcing.
    Civ5Ai_Autotest._phantomWait = Civ5Ai_Autotest._phantomWait or {}
    local waits = Civ5Ai_Autotest._phantomWait[playerID] or 0
    if Civ5Ai_Autotest._UnitsStillBlocking(blockingNow) and waits < 3 then
      Civ5Ai_Autotest._phantomWait[playerID] = waits + 1
      Civ5Ai_Util.Log(
        "autotest|CONTROL_ENDTURN|phantom_wait_net|player="
          .. tostring(playerID)
          .. "|waits="
          .. tostring(waits + 1)
          .. "|blocking="
          .. tostring(blockingNow)
      )
      Civ5Ai_Autotest._ReleaseUiFocus()
      return false, "phantom_wait_net|" .. tostring(blockingNow)
    end
    Civ5Ai_Autotest._phantomWait[playerID] = 0
    if not Civ5Ai_Autotest._UnitsStillBlocking(blockingNow) then
      Civ5Ai_Util.Log(
        "autotest|CONTROL_ENDTURN|phantom_cleared_after_endturns|player="
          .. tostring(playerID)
      )
    else
      Civ5Ai_Apply._UiTry("SetCanEndTurn", true)
      Civ5Ai_Apply._UiTry("SetMPAutoEndTurnEnabled", true)
      Civ5Ai_Util.Log(
        "autotest|CONTROL_ENDTURN|phantom_force_can_end_turn|player="
          .. tostring(playerID)
      )
    end
  end
  local can = true
  if Game.CanDoControl ~= nil then
    can = Game.CanDoControl(control) == true
  end
  if not can then
    Civ5Ai_Autotest._ReleaseUiFocus()
    if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._ClearLocalHumanEndTurnUi ~= nil then
      Civ5Ai_Apply._ClearLocalHumanEndTurnUi(playerID)
    end
    if Game.CanDoControl ~= nil then
      can = Game.CanDoControl(control) == true
    end
  end
  if not can then
    if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._LogCanDoControlDiag ~= nil then
      Civ5Ai_Apply._LogCanDoControlDiag(playerID, false)
    end
    -- Next Turn is already green when blocking==-1. The button click
    -- (ActionInfoPanel) calls DoControl without checking CanDoControl.
    -- skip_noop here left the seat hung with a green button.
    local cityUp = false
    if UI ~= nil and UI.IsCityScreenUp ~= nil then
      cityUp = UI.IsCityScreenUp() == true
    end
    if Civ5Ai_Autotest._NoEndTurnBlocking(blocking) and not cityUp then
      local busyN = 0
      local ordersN = 0
      if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._UnitsMovesDiag ~= nil then
        local _, n = Civ5Ai_Apply._UnitsMovesDiag(playerID)
        busyN = n or 0
      end
      if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._UnitsNeedingOrdersCount ~= nil then
        ordersN = Civ5Ai_Apply._UnitsNeedingOrdersCount(playerID) or 0
      end
      if ordersN > 0 then
        if Civ5Ai_Apply ~= nil and Civ5Ai_Apply.SkipUnorderedUnits ~= nil then
          Civ5Ai_Apply.SkipUnorderedUnits(playerID)
          if Civ5Ai_Apply._ClearLocalHumanEndTurnUi ~= nil then
            Civ5Ai_Apply._ClearLocalHumanEndTurnUi(playerID)
          end
          if Game.CanDoControl ~= nil then
            can = Game.CanDoControl(control) == true
          end
          if can then
            Game.DoControl(control)
            Civ5Ai_Autotest._PressEndTurnButton(playerID)
            Civ5Ai_Util.Log(
              "autotest|CONTROL_ENDTURN|blocking="
                .. tostring(blocking)
                .. "|can=true|after_skip_unordered"
            )
            return true, "skip_unordered"
          end
        end
        Civ5Ai_Util.Log(
          "autotest|CONTROL_ENDTURN|blocking="
            .. tostring(blocking)
            .. "|can=false|wait_busy|"
            .. tostring(ordersN)
        )
        return false, "unit_busy"
      end
      if busyN > 0 then
        Civ5Ai_Util.Log(
          "autotest|CONTROL_ENDTURN|blocking="
            .. tostring(blocking)
            .. "|can=false|busy_anim|"
            .. tostring(busyN)
        )
      end
      local sent = false
      if Network ~= nil and Network.HasSentNetTurnComplete ~= nil then
        sent = Network.HasSentNetTurnComplete() == true
      end
      Game.DoControl(control)
      Civ5Ai_Autotest._PressEndTurnButton(playerID)
      Civ5Ai_Util.Log(
        "autotest|CONTROL_ENDTURN|blocking="
          .. tostring(blocking)
          .. "|can=false|do_anyway|ctrl="
          .. tostring(control)
          .. "|sent="
          .. tostring(sent)
      )
      return true, "do_anyway"
    end
    local phantomCan = Civ5Ai_Autotest._UnitsStillBlocking(blocking)
      and Civ5Ai_Apply ~= nil
      and Civ5Ai_Apply._AllUnitsLookFinishedForEndTurn ~= nil
      and Civ5Ai_Apply._AllUnitsLookFinishedForEndTurn(playerID) == true
    if phantomCan then
      Civ5Ai_Apply._UiTry("SetCanEndTurn", true)
      Game.DoControl(control)
      Civ5Ai_Autotest._PressEndTurnButton(playerID)
      Civ5Ai_Util.Log(
        "autotest|CONTROL_ENDTURN|blocking="
          .. tostring(blocking)
          .. "|can=false|phantom_do_anyway"
      )
      return true, "phantom_do_anyway"
    end
    Civ5Ai_Util.Log(
      "autotest|CONTROL_ENDTURN|blocking="
        .. tostring(blocking)
        .. "|can=false|skip_noop"
    )
    return false, "can_false"
  end
  -- HostInbox DoControl alone is ignored; always press ActionInfoPanel Next Turn.
  Game.DoControl(control)
  Civ5Ai_Autotest._PressEndTurnButton(playerID)
  Civ5Ai_Util.Log(
    "autotest|CONTROL_ENDTURN|blocking="
      .. tostring(blocking)
      .. "|can="
      .. tostring(can)
      .. "|pressed=true"
  )
  return true, tostring(blocking)
end

function Civ5Ai_Autotest._TryEndTurnNow(playerID)
  local ok, detail = Civ5Ai_Autotest._RequestEndTurn(playerID)
  Civ5Ai_Util.Log(
    "bridge|CONTROL_ENDTURN|player="
      .. tostring(playerID)
      .. "|ok="
      .. tostring(ok)
      .. "|detail="
      .. tostring(detail)
  )
  return ok, detail
end

Civ5Ai_Autotest._humanEndTurnGen = Civ5Ai_Autotest._humanEndTurnGen or {}

function Civ5Ai_Autotest._BumpHumanEndTurnGen(playerID)
  Civ5Ai_Autotest._humanEndTurnGen[playerID] = (Civ5Ai_Autotest._humanEndTurnGen[playerID] or 0) + 1
  return Civ5Ai_Autotest._humanEndTurnGen[playerID]
end

function Civ5Ai_Autotest._HumanEndTurnStale(playerID, gen)
  return Civ5Ai_Autotest._humanEndTurnGen[playerID] ~= gen
end

function Civ5Ai_Autotest.EndHumanTurn(playerID)
  if Civ5Ai_Seats == nil or not Civ5Ai_Seats.IsLlmHuman(playerID) then
    return
  end
  -- Co-active used to redirect into _FinishManagedSeat / Civ5AiFinishSeat,
  -- which called setTurnActive(false) on engine-human seat 0 and crashed.
  -- Humans always end via CONTROL_ENDTURN below.
  if Civ5Ai_Autotest._stopped then
    Civ5Ai_Bridge._ReleasePulseSlot(playerID)
    return
  end
  if Game == nil or Game.GetActivePlayer == nil then
    Civ5Ai_Bridge._ReleasePulseSlot(playerID)
    return
  end
  local active = Game.GetActivePlayer()
  if active ~= playerID then
    Civ5Ai_Bridge._ReleaseNativeAi(playerID)
    Civ5Ai_Bridge._ReleasePulseSlot(playerID)
    return
  end
  local startTurn = Game.GetGameTurn()
  local endGen = Civ5Ai_Autotest._humanEndTurnGen[playerID] or 0
  Civ5Ai_Util.ScheduleTick(function()
    if Civ5Ai_Autotest._HumanEndTurnStale(playerID, endGen) then
      return false
    end
    if Civ5Ai_Autotest._stopped or Civ5Ai_Autotest._SeatTurnFinished(playerID, startTurn) then
      Civ5Ai_Bridge._ReleaseNativeAi(playerID)
      Civ5Ai_Bridge._ReleasePulseSlot(playerID)
      return false
    end
    if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._DismissBlockingPopups ~= nil then
      Civ5Ai_Apply._DismissBlockingPopups()
    end
    if Civ5Ai_Bridge._ApplyCpLimitedFallback ~= nil then
      Civ5Ai_Bridge._ApplyCpLimitedFallback(playerID)
    end
    if Civ5Ai_Apply ~= nil and Civ5Ai_Apply._ClearLocalHumanEndTurnBlockers ~= nil then
      Civ5Ai_Apply._ClearLocalHumanEndTurnBlockers(playerID)
    end
    local blocking = Civ5Ai_Autotest._EndTurnBlocking()
    if not Civ5Ai_Autotest._NoEndTurnBlocking(blocking) then
      Civ5Ai_Autotest._ResolveEndTurnBlocking(playerID, blocking)
    end
    -- Do not spam CONTROL_ENDTURN while managed peers are still turn-active.
    if Civ5Ai_Autotest._OtherSeatTurnActive(playerID) then
      return true
    end
    -- Unified finish retries CONTROL_ENDTURN; this tick clears blockers then
    -- presses even when CanDoControl is false (do_anyway when blocking is clear).
    Civ5Ai_Autotest._TryEndTurnNow(playerID)
    return true
  end)
end

function Civ5Ai_Autotest.RequestEndTurnNudge(reason)
  if not Civ5Ai_Config.IsAutotest() or Civ5Ai_Autotest._stopped then
    return
  end
  if not Civ5Ai_Config.IsSidecarLive() then
    return
  end
  local active = Game.GetActivePlayer()
  if Civ5Ai_Seats == nil or not Civ5Ai_Seats.IsLlmHuman(active) then
    return
  end
  Civ5Ai_Util.Log("nudge_enter|" .. tostring(reason or "autotest"))
end

function Civ5Ai_Autotest._DismissBeginJourney()
  -- LoadScreen "Begin your journey" calls Events.LoadScreenClose on ActivateButton click.
  if Events.LoadScreenClose then
    Events.LoadScreenClose()
  end
  if UI ~= nil and UI.SetDontShowPopups ~= nil then
    UI.SetDontShowPopups(false)
  end
  if Game ~= nil and Game.SetPausePlayer ~= nil then
    local unpauseAll = true
    if PreGame ~= nil and PreGame.IsMultiplayerGame ~= nil and PreGame.IsHotSeatGame ~= nil then
      unpauseAll = not PreGame.IsMultiplayerGame() and not PreGame.IsHotSeatGame()
    end
    if unpauseAll then
      Game.SetPausePlayer(-1)
    end
  end
  Civ5Ai_Util.Log("init|begin_journey|click")
end

function Civ5Ai_Autotest._ScheduleBeginJourneyDismiss(onReady)
  if Civ5Ai_Autotest._beginJourneyDismissed then
    if onReady ~= nil then
      onReady()
    end
    return
  end
  local attempts = 0
  Civ5Ai_Util.ScheduleTick(function()
    attempts = attempts + 1
    if Civ5Ai_Bridge.IsLoadScreenClosed() then
      Civ5Ai_Autotest._beginJourneyDismissed = true
      Civ5Ai_Util.Log("init|begin_journey|closed")
      if onReady ~= nil then
        onReady()
      end
      return false
    end
    Civ5Ai_Autotest._DismissBeginJourney()
    if Civ5Ai_Bridge.IsLoadScreenClosed() then
      Civ5Ai_Autotest._beginJourneyDismissed = true
      Civ5Ai_Util.Log("init|begin_journey|closed")
      if onReady ~= nil then
        onReady()
      end
      return false
    end
    if attempts >= 120 then
      Civ5Ai_Util.Log("init|begin_journey|timeout|attempts=" .. tostring(attempts))
      if onReady ~= nil then
        onReady()
      end
      return false
    end
    return true
  end)
end

function Civ5Ai_Autotest._DismissBlockers(playerID)
  if Civ5Ai_Apply ~= nil and Civ5Ai_Apply.ResolveFaithBlockers ~= nil then
    Civ5Ai_Apply.ResolveFaithBlockers(playerID)
  end
end

function Civ5Ai_Autotest.OnSequenceComplete()
  Civ5Ai_Util.Log("init|sequence_complete|turn=" .. tostring(Game.GetGameTurn()))
  local activePlayer = Game.GetActivePlayer()
  Civ5Ai_Autotest._ScheduleBeginJourneyDismiss(function()
    Civ5Ai_Autotest._DismissBlockers(activePlayer)
    Civ5Ai_Autotest._ArmAutoplay()
    if Civ5Ai_Bridge ~= nil then
      Civ5Ai_Bridge._RequestCoActiveManagedTurnPulses()
      Civ5Ai_Bridge._KickPulseQueue()
    end
    if Civ5Ai_Config.IsSidecarLive() then
      Civ5Ai_Autotest.RequestEndTurnNudge("sequence_complete")
    end
  end)
end

function Civ5Ai_Autotest.OnActivePlayerTurnStart()
  local turn = Game.GetGameTurn()
  Civ5Ai_Util.Log(
    "turn|active_start|turn=" .. tostring(turn) .. "|player=" .. tostring(Game.GetActivePlayer())
  )
  if not Civ5Ai_Autotest._autoplayArmed then
    Civ5Ai_Autotest._ArmAutoplay()
  end
  if Civ5Ai_Apply ~= nil and Civ5Ai_Apply.ResolveFaithBlockers ~= nil then
    Civ5Ai_Apply.ResolveFaithBlockers(Game.GetActivePlayer())
  end
end

function Civ5Ai_Autotest.AfterPulse(playerID)
  if not Civ5Ai_Config.IsAutotest() then
    return
  end
  local turn = Game.GetGameTurn()
  Civ5Ai_Util.Log("autotest|after_pulse|turn=" .. tostring(turn) .. "|player=" .. tostring(playerID))
  local winner = nil
  if Game.GetWinner ~= nil then
    winner = Game.GetWinner()
  end
  local victory = type(winner) == "number" and winner >= 0 and winner < 32
  if (victory or Civ5Ai_Autotest.ReachedStopTurn(turn))
      and Civ5Ai_Bridge._AllManagedPulsesFinished(turn) then
    Game.SetAIAutoPlay(0)
    Civ5Ai_Autotest._stopped = true
    if victory then
      Civ5Ai_Util.Log(
        "autotest|stop|turn=" .. tostring(turn) .. "|winner=" .. tostring(winner)
      )
    else
      Civ5Ai_Util.Log("autotest|stop|turn=" .. tostring(turn))
    end
  end
end
