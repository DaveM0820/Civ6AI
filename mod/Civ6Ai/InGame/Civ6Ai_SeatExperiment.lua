-- Gate 2 seat-type experiment: production vs Firaxis city AI, unit fallback probe.
Civ6Ai_SeatExperiment = Civ6Ai_SeatExperiment or {}

Civ6Ai_SeatExperiment._pulseState = Civ6Ai_SeatExperiment._pulseState or {}

function Civ6Ai_SeatExperiment._SessionDir(playerID)
  local root = Civ6Ai_Config.RootDir()
  local sessionId = Civ6Ai_Bridge.SessionId()
  return Civ6Ai_Util.JoinPath(root, "sessions", sessionId, Civ6Ai_Util.PlayerId(playerID))
end

function Civ6Ai_SeatExperiment._AppendJsonLine(path, payload)
  local line = Civ6Ai_SeatExperiment._EncodeEvent(payload)
  if io and io.open then
    local file = io.open(path, "a")
    if file ~= nil then
      file:write(line .. "\n")
      file:close()
      return true
    end
  end
  Civ6Ai_Util.Log("seat_exp|log_fallback|" .. line)
  return false
end

function Civ6Ai_SeatExperiment._EncodeEvent(payload)
  local parts = {}
  for key, value in pairs(payload) do
    table.insert(parts, Civ6Ai_Util.EscapeJson(key) .. ":" .. Civ6Ai_SeatExperiment._EncodeValue(value))
  end
  return "{" .. table.concat(parts, ",") .. "}"
end

function Civ6Ai_SeatExperiment._EncodeValue(value)
  if type(value) == "table" then
    if #value > 0 then
      local items = {}
      for _, item in ipairs(value) do
        table.insert(items, Civ6Ai_SeatExperiment._EncodeValue(item))
      end
      return "[" .. table.concat(items, ",") .. "]"
    end
    local parts = {}
    for key, child in pairs(value) do
      table.insert(parts, Civ6Ai_Util.EscapeJson(key) .. ":" .. Civ6Ai_SeatExperiment._EncodeValue(child))
    end
    return "{" .. table.concat(parts, ",") .. "}"
  end
  if type(value) == "boolean" then
    return value and "true" or "false"
  end
  if type(value) == "number" then
    return tostring(value)
  end
  if value == nil then
    return "null"
  end
  return Civ6Ai_Util.EscapeJson(value)
end

function Civ6Ai_SeatExperiment._LogEvent(playerID, phase, extra)
  local payload = {
    event = "seat_experiment",
    phase = phase,
    turn = Game.GetCurrentGameTurn(),
    player_id = Civ6Ai_Util.PlayerId(playerID),
    seat_human = Players[playerID]:IsHuman(),
    seat_managed = Civ6Ai_Config.IsManagedSeat(playerID),
  }
  if extra ~= nil then
    for key, value in pairs(extra) do
      payload[key] = value
    end
  end
  local path = Civ6Ai_Util.JoinPath(Civ6Ai_SeatExperiment._SessionDir(playerID), "seat-experiment.jsonl")
  Civ6Ai_SeatExperiment._AppendJsonLine(path, payload)
end

function Civ6Ai_SeatExperiment.BeginPulse(playerID)
  if not Civ6Ai_Config.IsSeatExperiment() then
    return
  end
  local cityId, buildId = Civ6Ai_Production.FindExperimentTarget(playerID)
  local state = {
    turn = Game.GetCurrentGameTurn(),
    experiment_city_id = cityId,
    experiment_target = buildId,
    pre_apply = Civ6Ai_Production.CollectProductionMap(playerID),
    units_with_moves_pre = Civ6Ai_Production.CountUnitsWithMoves(playerID),
    post_apply = nil,
    units_with_moves_post_apply = nil,
  }
  Civ6Ai_SeatExperiment._pulseState[playerID] = state
  Civ6Ai_SeatExperiment._LogEvent(playerID, "turn_start", {
    production = state.pre_apply,
    units_with_moves = state.units_with_moves_pre,
    experiment_city_id = cityId,
    experiment_target = buildId,
  })
end

function Civ6Ai_SeatExperiment.AfterApply(playerID)
  if not Civ6Ai_Config.IsSeatExperiment() then
    return
  end
  local state = Civ6Ai_SeatExperiment._pulseState[playerID]
  if state == nil then
    return
  end
  state.post_apply = Civ6Ai_Production.CollectProductionMap(playerID)
  state.units_with_moves_post_apply = Civ6Ai_Production.CountUnitsWithMoves(playerID)
  local cityId = state.experiment_city_id
  local observed = nil
  if cityId ~= nil and state.post_apply ~= nil then
    observed = state.post_apply[cityId]
  end
  local apply_ok = false
  if state.experiment_target ~= nil and observed == state.experiment_target then
    apply_ok = true
  end
  Civ6Ai_SeatExperiment._LogEvent(playerID, "post_llm_apply", {
    production = state.post_apply,
    units_with_moves = state.units_with_moves_post_apply,
    experiment_city_id = cityId,
    experiment_target = state.experiment_target,
    observed_production = observed,
    llm_apply_ok = apply_ok,
  })
end

function Civ6Ai_SeatExperiment.OnPlayerTurnActivated(playerID)
  if not Civ6Ai_Config.IsSeatExperiment() then
    return
  end
  if not Civ6Ai_Config.IsManagedSeat(playerID) then
    return
  end
  local state = Civ6Ai_SeatExperiment._pulseState[playerID]
  if state == nil or state.turn ~= Game.GetCurrentGameTurn() then
    return
  end
  local postNative = Civ6Ai_Production.CollectProductionMap(playerID)
  local unitsPostNative = Civ6Ai_Production.CountUnitsWithMoves(playerID)
  local cityId = state.experiment_city_id
  local expected = state.experiment_target
  local observedNative = nil
  if cityId ~= nil then
    observedNative = postNative[cityId]
  end
  local production_overwritten = false
  if expected ~= nil and state.post_apply ~= nil and cityId ~= nil then
    local observedApply = state.post_apply[cityId]
    if observedApply == expected and observedNative ~= expected then
      production_overwritten = true
    end
  end
  local units_moved_by_native = false
  if state.units_with_moves_post_apply ~= nil and unitsPostNative < state.units_with_moves_post_apply then
    units_moved_by_native = true
  end
  Civ6Ai_SeatExperiment._LogEvent(playerID, "post_native_ai", {
    production = postNative,
    units_with_moves = unitsPostNative,
    experiment_city_id = cityId,
    experiment_target = expected,
    observed_production = observedNative,
    production_overwritten = production_overwritten,
    units_moved_by_native = units_moved_by_native,
  })
  Civ6Ai_SeatExperiment._pulseState[playerID] = nil
end

function Civ6Ai_SeatExperiment.Initialize()
  if Civ6Ai_Config.IsSeatExperiment() then
    Civ6Ai_Util.Log("seat_exp|enabled")
  end
end
