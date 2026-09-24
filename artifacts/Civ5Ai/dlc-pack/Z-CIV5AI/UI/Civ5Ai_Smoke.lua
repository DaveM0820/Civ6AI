-- Civ5Ai turn-loop smoke (STEP 1). No sidecar, no snapshot.
local STOP_TURN = 3

print("CIV5AI|smoke|file_loaded")

local autoplayArmed = false

local function Civ5Ai_ArmAutoplay()
  if autoplayArmed then
    return
  end
  Game.SetPausePlayer(-1)
  Game.SetAIAutoPlay(STOP_TURN + 2)
  autoplayArmed = true
  print("CIV5AI|autotest|autoplay_armed|n=" .. tostring(STOP_TURN + 2))
end

local function Civ5Ai_AutoDismissBlockers()
  if Events.SerialEventDawnOfManHide then
    Events.SerialEventDawnOfManHide()
    print("CIV5AI|init|dawn_hidden")
  end

  local active = Game.GetActivePlayer()
  if Game.GetAvailablePantheonBeliefs then
    for _, beliefKey in ipairs(Game.GetAvailablePantheonBeliefs()) do
      local belief = GameInfo.Beliefs[beliefKey]
      if belief then
        Network.SendFoundPantheon(active, belief.ID)
        print("CIV5AI|autotest|pantheon|chosen|id=" .. tostring(belief.ID))
        break
      end
    end
  end

  print("CIV5AI|init|load_screen_close")
end

Events.SequenceGameInitComplete.Add(function()
  print("CIV5AI|init|sequence_complete|turn=" .. tostring(Game.GetGameTurn()))
  Civ5Ai_AutoDismissBlockers()
  Civ5Ai_ArmAutoplay()
end)

Events.LoadScreenClose.Add(function()
  print("CIV5AI|init|load_screen_close")
end)

Events.SerialEventDawnOfManShow.Add(function()
  print("CIV5AI|init|dawn_show")
  if Events.SerialEventDawnOfManHide then
    Events.SerialEventDawnOfManHide()
  end
  print("CIV5AI|init|dawn_hidden")
end)

Events.ActivePlayerTurnStart.Add(function()
  local turn = Game.GetGameTurn()
  print(
    "CIV5AI|turn|active_start|turn="
      .. tostring(turn)
      .. "|player="
      .. tostring(Game.GetActivePlayer())
  )
  if not autoplayArmed then
    Civ5Ai_ArmAutoplay()
  end
  if turn >= STOP_TURN then
    Game.SetAIAutoPlay(0)
    print("CIV5AI|autotest|stop|turn=" .. tostring(turn))
  end
end)

if GameEvents and GameEvents.PlayerDoTurn then
  GameEvents.PlayerDoTurn.Add(function(playerID)
    print(
      "CIV5AI|turn|player_do|turn="
        .. tostring(Game.GetGameTurn())
        .. "|player="
        .. tostring(playerID)
    )
  end)
else
  print("CIV5AI|smoke|player_do_turn_unavailable")
end
