-- Seat roles and per-seat pulse step. Engine turn events start pulses;
-- this module does not run other seats from human step 6.
Civ5Ai_Seats = Civ5Ai_Seats or {}

Civ5Ai_Seats.ROLE_HUMAN = "human"
Civ5Ai_Seats.ROLE_LLM_HUMAN = "llm_human"
Civ5Ai_Seats.ROLE_CP = "cp"
Civ5Ai_Seats.ROLE_LLM_THEN_CP = "llm_then_cp"

Civ5Ai_Seats.STEP_IDLE = "idle"
Civ5Ai_Seats.STEP_DONE = "done"

Civ5Ai_Seats._STEP_LABELS = {
  [1] = "1 snap",
  [2] = "2 write",
  [3] = "3 LLM",
  [4] = "4 parse",
  [5] = "5 apply",
  [6] = "6 end",
}

function Civ5Ai_Seats.Initialize()
  Civ5Ai_Seats._humanSeat = "llm_human"
  Civ5Ai_Seats._computerMode = "llm_human"
  Civ5Ai_Seats._majorCount = 4
  if Civ5Ai_Paths ~= nil then
    if Civ5Ai_Paths.HumanSeat ~= nil and Civ5Ai_Paths.HumanSeat ~= "" then
      Civ5Ai_Seats._humanSeat = tostring(Civ5Ai_Paths.HumanSeat)
    end
    if Civ5Ai_Paths.ComputerMode ~= nil and Civ5Ai_Paths.ComputerMode ~= "" then
      Civ5Ai_Seats._computerMode = tostring(Civ5Ai_Paths.ComputerMode)
    end
    if Civ5Ai_Paths.MajorCount ~= nil then
      Civ5Ai_Seats._majorCount = tonumber(Civ5Ai_Paths.MajorCount) or 4
    end
  end
  if Civ5Ai_Seats._humanSeat ~= Civ5Ai_Seats.ROLE_HUMAN
      and Civ5Ai_Seats._humanSeat ~= Civ5Ai_Seats.ROLE_LLM_HUMAN then
    Civ5Ai_Seats._humanSeat = Civ5Ai_Seats.ROLE_LLM_HUMAN
  end
  if Civ5Ai_Seats._computerMode ~= Civ5Ai_Seats.ROLE_CP
      and Civ5Ai_Seats._computerMode ~= Civ5Ai_Seats.ROLE_LLM_THEN_CP
      and Civ5Ai_Seats._computerMode ~= Civ5Ai_Seats.ROLE_LLM_HUMAN then
    Civ5Ai_Seats._computerMode = Civ5Ai_Seats.ROLE_LLM_HUMAN
  end
  Civ5Ai_Seats._step = {}
  Civ5Ai_Seats._stepTurn = {}
  Civ5Ai_Seats._EnsureStepEvent()
  Civ5Ai_Util.Log(
    "seats|init|human="
      .. Civ5Ai_Seats._humanSeat
      .. "|computer="
      .. Civ5Ai_Seats._computerMode
      .. "|majors="
      .. tostring(Civ5Ai_Seats._majorCount)
      .. "|full_llm_computer="
      .. tostring(Civ5Ai_Seats._computerMode == Civ5Ai_Seats.ROLE_LLM_HUMAN)
      .. "|fair_handicap="
      .. tostring(Civ5Ai_Seats.UsesFairHandicap())
  )
end

function Civ5Ai_Seats._EnsureStepEvent()
  if LuaEvents == nil then
    return
  end
  if LuaEvents.Civ5AiSeatStepChanged ~= nil then
    return
  end
  local handlers = {}
  local event = {}
  event.Add = function(fn)
    table.insert(handlers, fn)
  end
  LuaEvents.Civ5AiSeatStepChanged = setmetatable(event, {
    __call = function(_, playerID)
      for _, fn in ipairs(handlers) do
        fn(playerID)
      end
    end,
  })
end

function Civ5Ai_Seats._GameTurn()
  if Game ~= nil and Game.GetGameTurn ~= nil then
    return Game.GetGameTurn()
  end
  return 0
end

function Civ5Ai_Seats._IsAliveMajor(playerID)
  local player = Players[playerID]
  if player == nil or not player:IsAlive() or player:IsBarbarian() then
    return false
  end
  if player.IsMinorCiv ~= nil and player:IsMinorCiv() then
    return false
  end
  return true
end

function Civ5Ai_Seats._InManagedList(playerID)
  return Civ5Ai_Config ~= nil
    and Civ5Ai_Config._managedSeats ~= nil
    and Civ5Ai_Config._managedSeats[playerID] == true
end

function Civ5Ai_Seats.IsLocalHuman(playerID)
  local player = Players[playerID]
  return player ~= nil and player:IsHuman() == true
end

-- Seat that uses CONTROL_ENDTURN / EndHumanTurn on this machine.
-- SP autoplay: seat 0 only. Hot seat / LAN: whichever seat is locally active.
function Civ5Ai_Seats.IsActiveLocalPlayer(playerID)
  local seat = tonumber(playerID)
  if seat == nil then
    return false
  end
  if Game == nil or Game.GetActivePlayer == nil then
    return seat == 0
  end
  if PreGame ~= nil and PreGame.IsHotSeatGame ~= nil and PreGame.IsHotSeatGame() then
    return Game.GetActivePlayer() == seat
  end
  if Game.IsNetworkMultiPlayer ~= nil and Game.IsNetworkMultiPlayer() then
    return Game.GetActivePlayer() == seat and Civ5Ai_Seats.IsLocalHuman(seat)
  end
  return seat == 0
end

function Civ5Ai_Seats.UsesFairHandicap()
  if Civ5Ai_FairHandicap == false then
    return false
  end
  if Civ5Ai_FairHandicap == true then
    return true
  end
  if Civ5Ai_Paths ~= nil and Civ5Ai_Paths.FairHandicap ~= nil then
    local raw = Civ5Ai_Paths.FairHandicap
    if raw == false or raw == 0 or raw == "0" then
      return false
    end
    if raw == true or raw == 1 or raw == "1" then
      return true
    end
  end
  local mode = Civ5Ai_Seats._computerMode
  if mode == nil or mode == "" then
    if Civ5Ai_ComputerMode ~= nil and Civ5Ai_ComputerMode ~= "" then
      mode = Civ5Ai_ComputerMode
    elseif Civ5Ai_Paths ~= nil and Civ5Ai_Paths.ComputerMode ~= nil and Civ5Ai_Paths.ComputerMode ~= "" then
      mode = Civ5Ai_Paths.ComputerMode
    else
      mode = Civ5Ai_Seats.ROLE_LLM_HUMAN
    end
  end
  if mode ~= Civ5Ai_Seats.ROLE_LLM_HUMAN then
    return false
  end
  local humanSeat = Civ5Ai_Seats._humanSeat
  if humanSeat == nil or humanSeat == "" then
    if Civ5Ai_HumanSeat ~= nil and Civ5Ai_HumanSeat ~= "" then
      humanSeat = Civ5Ai_HumanSeat
    elseif Civ5Ai_Paths ~= nil and Civ5Ai_Paths.HumanSeat ~= nil and Civ5Ai_Paths.HumanSeat ~= "" then
      humanSeat = Civ5Ai_Paths.HumanSeat
    else
      humanSeat = Civ5Ai_Seats.ROLE_LLM_HUMAN
    end
  end
  return humanSeat == Civ5Ai_Seats.ROLE_LLM_HUMAN
end

function Civ5Ai_Seats.Role(playerID)
  if not Civ5Ai_Seats._IsAliveMajor(playerID) then
    return Civ5Ai_Seats.ROLE_CP
  end
  if Civ5Ai_Seats.IsLocalHuman(playerID) then
    if Civ5Ai_Seats._InManagedList(playerID) then
      return Civ5Ai_Seats._humanSeat
    end
    return Civ5Ai_Seats.ROLE_HUMAN
  end
  if Civ5Ai_Seats._InManagedList(playerID) then
    return Civ5Ai_Seats._computerMode
  end
  return Civ5Ai_Seats.ROLE_CP
end

function Civ5Ai_Seats.ShouldPulse(playerID)
  if Civ5Ai_Config == nil or not Civ5Ai_Config.IsEnabled() then
    return false
  end
  local role = Civ5Ai_Seats.Role(playerID)
  return role == Civ5Ai_Seats.ROLE_LLM_HUMAN or role == Civ5Ai_Seats.ROLE_LLM_THEN_CP
end

function Civ5Ai_Seats.IsLlmHuman(playerID)
  return Civ5Ai_Seats.Role(playerID) == Civ5Ai_Seats.ROLE_LLM_HUMAN
end

function Civ5Ai_Seats.IsLlmThenCp(playerID)
  return Civ5Ai_Seats.Role(playerID) == Civ5Ai_Seats.ROLE_LLM_THEN_CP
end

-- Full LLM control: LLM owns strategy; CP limited fallback handles only
-- unordered units and empty-city production after apply.
function Civ5Ai_Seats.UsesFullLlmControl(playerID)
  if not Civ5Ai_Seats.ShouldPulse(playerID) then
    return false
  end
  return not Civ5Ai_Seats.IsLlmThenCp(playerID)
end

function Civ5Ai_Seats.UsesCpLimitedFallback(playerID)
  return Civ5Ai_Seats.UsesFullLlmControl(playerID)
end

function Civ5Ai_Seats.UsesUiApply(playerID)
  -- SelectUnit / city-screen UI follows the local camera. Using this for
  -- every llm_human seat (fair-handicap 1-3) pans the minimap onto other
  -- civ start plots and leaks them onto parchment.
  return Civ5Ai_Seats.IsActiveLocalPlayer(playerID)
end

function Civ5Ai_Seats._EnsureTurn(playerID)
  local turn = Civ5Ai_Seats._GameTurn()
  if Civ5Ai_Seats._stepTurn[playerID] ~= turn then
    Civ5Ai_Seats._stepTurn[playerID] = turn
    Civ5Ai_Seats._step[playerID] = Civ5Ai_Seats.STEP_IDLE
  end
end

function Civ5Ai_Seats.Step(playerID)
  Civ5Ai_Seats._EnsureTurn(playerID)
  return Civ5Ai_Seats._step[playerID] or Civ5Ai_Seats.STEP_IDLE
end

function Civ5Ai_Seats.StepLabel(playerID)
  local step = Civ5Ai_Seats.Step(playerID)
  if step == Civ5Ai_Seats.STEP_IDLE then
    return nil
  end
  if step == Civ5Ai_Seats.STEP_DONE then
    return "done"
  end
  if type(step) == "number" then
    return Civ5Ai_Seats._STEP_LABELS[step] or (tostring(step) .. "/6")
  end
  return tostring(step)
end

function Civ5Ai_Seats._NotifyStepChanged(playerID)
  if LuaEvents ~= nil and LuaEvents.Civ5AiSeatStepChanged ~= nil then
    LuaEvents.Civ5AiSeatStepChanged(playerID)
  end
end

function Civ5Ai_Seats.SetStep(playerID, step)
  Civ5Ai_Seats._EnsureTurn(playerID)
  if Civ5Ai_Seats._step[playerID] == step then
    return
  end
  Civ5Ai_Seats._step[playerID] = step
  Civ5Ai_Seats._NotifyStepChanged(playerID)
end

function Civ5Ai_Seats.MarkDone(playerID)
  Civ5Ai_Seats.SetStep(playerID, Civ5Ai_Seats.STEP_DONE)
end
