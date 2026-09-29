-- Civ6Ai order channel (interface side). In a network game every model order
-- for an AI seat goes out as a synced EXECUTE_SCRIPT player operation, handled
-- on every PC by Gameplay/Civ6Ai_Orders.lua. This file never changes game
-- state itself.
--
-- Host: SendDecision turns a model decision into a batch of orders, keeps
-- seq -> command locally, and writes each command's real result to
-- apply-results.jsonl once the gameplay handler has run it (results arrive a
-- moment later, not during the send).
-- Every PC: a few seconds into each turn it reports its own checksum for the
-- turn, so the host's log shows whether the other PCs still match.
Civ6Ai_OrderChannel = Civ6Ai_OrderChannel or {}

Civ6Ai_OrderChannel.K = {
  MOVE = 1, RESEARCH = 2, CIVIC = 3, FOUND = 4, SKIP = 5, FORTIFY = 6, ATTACK = 7, RESOLVE = 8, PRIORITY = 9,
  GOVERNMENT = 10, POLICY = 11, PANTHEON = 12, RELIGION = 13, GP_RECRUIT = 14, GP_PATRONIZE = 15, GOVERNOR = 16,
  HOLD = 20, REPORT = 30, PING = 40, TEST_MODE = 49, TEST_INTROSPECT = 50, TEST_SPAWN_ENEMY = 51,
  TEST_MELEE_MOVE = 52, TEST_SCRIPTED_COMBAT = 53, TEST_SCRIPTED_PRODUCTION = 54, TEST_IMPROVEMENT = 55,
  TEST_EXPERIENCE = 56, TEST_FAR_MOVE = 57, TEST_COMBAT_PROBE = 58, TEST_DAMAGE_CHECK = 59,
  TEST_RESOLVED_ATTACK = 60, TEST_API_SURVEY = 61,
  TEST_PRODUCTION_STEER = 62, TEST_FORCE_BUILD = 63, TEST_PRIORITY = 64,
}
Civ6Ai_OrderChannel.KIND_BY_COMMAND = {
  move_unit = 1, set_research_tech = 2, set_research_civic = 3, found_city = 4, unit_skip = 5,
  unit_posture_fortify = 6, attack_target = 7, set_build_priority = 9,
  change_government = 10, set_policies = 11, found_pantheon = 12, found_religion = 13,
  recruit_great_person = 14, patronize_great_person = 15,
}
-- Kinds the gameplay side collects into a batch (B/J/N); others apply at once.
Civ6Ai_OrderChannel.BATCHED_KINDS = { [1] = true, [2] = true, [3] = true, [4] = true, [5] = true, [6] = true, [7] = true }
Civ6Ai_OrderChannel.RESULT_TIMEOUT_SECONDS = 45
Civ6Ai_OrderChannel.REPORT_DELAY_SECONDS = 5
Civ6Ai_OrderChannel._counter = Civ6Ai_OrderChannel._counter or 0
Civ6Ai_OrderChannel._batch = Civ6Ai_OrderChannel._batch or 0
Civ6Ai_OrderChannel._pending = Civ6Ai_OrderChannel._pending or {}
Civ6Ai_OrderChannel._resultCursor = Civ6Ai_OrderChannel._resultCursor or 0

local function log(s)
  if Civ6Ai_Util ~= nil and Civ6Ai_Util.Log ~= nil then
    Civ6Ai_Util.Log("order_channel|" .. s)
  else
    print("CIV6AI|order_channel|" .. s)
  end
end

function Civ6Ai_OrderChannel.IsNetworkGame()
  return GameConfiguration ~= nil and GameConfiguration.IsNetworkMultiplayer ~= nil
    and GameConfiguration.IsNetworkMultiplayer() == true
end

-- The synced channel is used in every network game. Hot-seat and single
-- player keep the direct routes (one PC, nothing to keep in sync).
function Civ6Ai_OrderChannel.IsActive()
  return Civ6Ai_OrderChannel.IsNetworkGame()
end

function Civ6Ai_OrderChannel._Shared()
  ExposedMembers.Civ6Ai = ExposedMembers.Civ6Ai or {}
  return ExposedMembers.Civ6Ai
end

function Civ6Ai_OrderChannel._Now()
  if Automation ~= nil and Automation.GetTime ~= nil then
    return Automation.GetTime()
  end
  if UI ~= nil and UI.GetElapsedTime ~= nil then
    return UI.GetElapsedTime()
  end
  return os ~= nil and os.clock ~= nil and os.clock() or 0
end

-- Send one order. Returns seq (or nil when the request could not be made).
function Civ6Ai_OrderChannel.Send(kind, fields, turnOverride)
  if UI == nil or UI.RequestPlayerOperation == nil or PlayerOperations == nil or PlayerOperations.EXECUTE_SCRIPT == nil then
    log("send_unavailable|kind=" .. tostring(kind))
    return nil
  end
  local me = Game.GetLocalPlayer()
  Civ6Ai_OrderChannel._counter = Civ6Ai_OrderChannel._counter + 1
  local params = {
    OnStart = "Civ6AiOrder",
    K = kind,
    T = turnOverride or Game.GetCurrentGameTurn(),
    S = me * 1000000 + Civ6Ai_OrderChannel._counter,
  }
  for k, v in pairs(fields or {}) do
    params[k] = v
  end
  local ok, err = pcall(UI.RequestPlayerOperation, me, PlayerOperations.EXECUTE_SCRIPT, params)
  local line = "send|seq=" .. params.S .. "|kind=" .. tostring(kind) .. "|turn=" .. tostring(params.T)
  for _, key in ipairs({ "P", "U", "X", "Y", "I", "V", "B", "J", "N" }) do
    if params[key] ~= nil then
      line = line .. "|" .. key .. "=" .. tostring(params[key])
    end
  end
  log(line .. "|ok=" .. tostring(ok) .. (ok and "" or ("|err=" .. tostring(err))))
  if not ok then
    return nil
  end
  return params.S
end

-- Integer fields for one model command, or nil, reason when it has no synced
-- route.
function Civ6Ai_OrderChannel._Fields(playerID, command)
  local kind = Civ6Ai_OrderChannel.KIND_BY_COMMAND[command.kind or ""]
  if kind == nil then
    if command.kind == "queue_production" then
      return nil, "production_no_mp_route"
    end
    if command.kind == "appoint_governor" or command.kind == "assign_governor" or command.kind == "promote_governor" then
      return nil, "governors cannot be set by a synced game script in a network game (no gameplay route); "
        .. "the game's own AI manages this seat's governors"
    end
    return nil, "unsupported_kind"
  end
  local args = command.arguments or {}
  local f = { K = kind, P = playerID }
  if args.unit_id ~= nil then
    f.U = Civ6Ai_Apply._ParseUnitNumericId(args.unit_id)
    if f.U == nil then
      return nil, "missing_unit_numeric_id"
    end
  end
  if kind == 1 or kind == 7 then
    local x, y = Civ6Ai_Apply._ResolveTargetCoords(args)
    if f.U == nil or x == nil or y == nil then
      return nil, "missing_unit_or_target"
    end
    f.X, f.Y = x, y
  elseif kind == 2 then
    local row = args.tech_id ~= nil and GameInfo.Technologies[args.tech_id] or nil
    if row == nil then
      return nil, args.tech_id == nil and "missing_tech_id" or "invalid_tech"
    end
    f.I = row.Index
  elseif kind == 3 then
    local id = args.civic_id or args.tech_id
    local row = id ~= nil and GameInfo.Civics[id] or nil
    if row == nil then
      return nil, id == nil and "missing_civic_id" or "invalid_civic"
    end
    f.I = row.Index
  elseif kind == 9 then
    local id, level = tonumber(args.priority_id), tonumber(args.priority_level)
    if id == nil or level == nil then
      return nil, "missing_priority"
    end
    f.I, f.X = id, level
  elseif kind == 10 then
    local row = args.government_id ~= nil and GameInfo.Governments[args.government_id] or nil
    if row == nil then
      return nil, "unknown government " .. tostring(args.government_id)
    end
    f.I = row.Index
  elseif kind == 11 then
    -- One order per slot; SendDecision expands the list.
    local plan, why = Civ6Ai_Apply._ParsePolicySlots(args.slots)
    if plan == nil then
      return nil, why
    end
    local list = {}
    for _, e in ipairs(plan) do
      local idx = -1
      if string.upper(e.policy) ~= "NONE" then
        local prow = GameInfo.Policies[e.policy] or GameInfo.Policies["POLICY_" .. e.policy]
        if prow == nil then
          return nil, "unknown policy card " .. e.policy
        end
        idx = prow.Index
      end
      list[#list + 1] = { K = kind, P = playerID, X = e.slot, I = idx }
    end
    return list, "", true
  elseif kind == 12 then
    local row = args.belief_id ~= nil and GameInfo.Beliefs[args.belief_id] or nil
    if row == nil then
      return nil, "unknown belief " .. tostring(args.belief_id)
    end
    f.I = row.Index
  elseif kind == 13 then
    local row = args.religion_id ~= nil and GameInfo.Religions[args.religion_id] or nil
    if row == nil then
      return nil, "unknown religion " .. tostring(args.religion_id)
    end
    f.I = row.Index
    local b = {}
    for id in string.gmatch(tostring(args.belief_ids or ""), "[%w_]+") do
      local brow = GameInfo.Beliefs[id]
      if brow == nil then
        return nil, "unknown belief " .. id
      end
      b[#b + 1] = brow.Index
    end
    f.X, f.Y = b[1] or -1, b[2] or -1
    f.U = f.U or -1
  elseif kind == 14 or kind == 15 then
    local row = args.individual_id ~= nil and GameInfo.GreatPersonIndividuals[args.individual_id] or nil
    if row == nil then
      return nil, "unknown great person " .. tostring(args.individual_id)
    end
    f.I = row.Index
    f.X = string.lower(tostring(args.yield or "gold")) == "faith" and 1 or 0
  elseif f.U == nil then
    return nil, "missing_unit_id"
  end
  return f, ""
end

-- Send a whole model decision for one AI seat as one batch.
function Civ6Ai_OrderChannel.SendDecision(playerID, decision)
  local orders = {}
  for _, command in ipairs(decision.commands or {}) do
    local f, why, many = Civ6Ai_OrderChannel._Fields(playerID, command)
    if f == nil then
      Civ6Ai_Apply._RecordResult(playerID, command, false, why, command.arguments or {})
      log("no_route|player=" .. tostring(playerID) .. "|kind=" .. tostring(command.kind) .. "|reason=" .. tostring(why))
    elseif many then
      for _, one in ipairs(f) do
        orders[#orders + 1] = { fields = one, command = command }
      end
    else
      orders[#orders + 1] = { fields = f, command = command }
    end
  end
  if #orders == 0 then
    return 0
  end
  Civ6Ai_OrderChannel._batch = Civ6Ai_OrderChannel._batch + 1
  local batch = Game.GetLocalPlayer() * 100000 + Civ6Ai_OrderChannel._batch
  local sent = 0
  -- Only unit/research orders are batched on the gameplay side; numbering the
  -- others too would leave the batch waiting for an index that never comes.
  local batchedCount, j = 0, 0
  for _, entry in ipairs(orders) do
    if Civ6Ai_OrderChannel.BATCHED_KINDS[entry.fields.K] then
      batchedCount = batchedCount + 1
    end
  end
  for _, entry in ipairs(orders) do
    local f = entry.fields
    if Civ6Ai_OrderChannel.BATCHED_KINDS[f.K] then
      j = j + 1
      f.B, f.J, f.N = batch, j, batchedCount
    end
    local kind = f.K
    f.K = nil
    local seq = Civ6Ai_OrderChannel.Send(kind, f)
    if seq ~= nil then
      Civ6Ai_OrderChannel._pending[seq] = { playerID = playerID, command = entry.command, sentAt = Civ6Ai_OrderChannel._Now() }
      sent = sent + 1
    else
      Civ6Ai_Apply._RecordResult(playerID, entry.command, false, "send_failed", entry.command.arguments or {})
    end
  end
  Civ6Ai_OrderChannel._EnsureResultPump()
  return sent
end

-- Finish the turn for an AI seat's unordered units (synced).
function Civ6Ai_OrderChannel.Resolve(playerID)
  return Civ6Ai_OrderChannel.Send(Civ6Ai_OrderChannel.K.RESOLVE, { P = playerID }) ~= nil
end

-- Make sure the given AI seats have the synced turn-start freeze on. Sent once
-- per seat per turn at most, and only while the synced value is not already on.
Civ6Ai_OrderChannel._holdSent = Civ6Ai_OrderChannel._holdSent or {}
function Civ6Ai_OrderChannel.EnsureHolds(seats)
  local turn = Game.GetCurrentGameTurn()
  for _, seat in ipairs(seats or {}) do
    local p = Players[seat]
    if p ~= nil and not p:IsHuman() and tonumber((Game:GetProperty("CIV6AI_HOLD_" .. tostring(seat))) or 0) ~= 1
        and Civ6Ai_OrderChannel._holdSent[seat] ~= turn then
      Civ6Ai_OrderChannel._holdSent[seat] = turn
      Civ6Ai_OrderChannel.Send(Civ6Ai_OrderChannel.K.HOLD, { P = seat, V = 1 })
    end
  end
end

-- ---------------------------------------------------------------------------
-- Results
-- ---------------------------------------------------------------------------
function Civ6Ai_OrderChannel.DrainResults()
  local shared = Civ6Ai_OrderChannel._Shared()
  local results = shared.OrderResults or {}
  local me = Game.GetLocalPlayer()
  for _, r in ipairs(results) do
    if r.sender == me and Civ6Ai_OrderChannel._pending[r.seq] ~= nil then
      local entry = Civ6Ai_OrderChannel._pending[r.seq]
      Civ6Ai_OrderChannel._pending[r.seq] = nil
      Civ6Ai_Apply._RecordResult(entry.playerID, entry.command, r.ok == true, r.reason, entry.command.arguments or {})
      if r.ok and entry.command.arguments ~= nil and entry.command.arguments.unit_id ~= nil then
        local numeric = Civ6Ai_Apply._ParseUnitNumericId(entry.command.arguments.unit_id)
        Civ6Ai_Apply._orderedUnits = Civ6Ai_Apply._orderedUnits or {}
        Civ6Ai_Apply._orderedUnits[entry.playerID] = Civ6Ai_Apply._orderedUnits[entry.playerID] or {}
        if numeric ~= nil then
          Civ6Ai_Apply._orderedUnits[entry.playerID][numeric] = true
        end
      end
    end
  end
  local now = Civ6Ai_OrderChannel._Now()
  local left = 0
  for seq, entry in pairs(Civ6Ai_OrderChannel._pending) do
    if now - (entry.sentAt or now) > Civ6Ai_OrderChannel.RESULT_TIMEOUT_SECONDS then
      Civ6Ai_OrderChannel._pending[seq] = nil
      Civ6Ai_Apply._RecordResult(entry.playerID, entry.command, false, "no_result_from_gameplay", entry.command.arguments or {})
      log("result_timeout|seq=" .. tostring(seq))
    else
      left = left + 1
    end
  end
  return left
end

function Civ6Ai_OrderChannel._EnsureResultPump()
  if Civ6Ai_OrderChannel._pumping then
    return
  end
  Civ6Ai_OrderChannel._pumping = true
  Civ6Ai_Util.ScheduleTick(function()
    local left = Civ6Ai_OrderChannel.DrainResults()
    if left == 0 then
      Civ6Ai_OrderChannel._pumping = false
      return false
    end
    return true
  end)
end

-- ---------------------------------------------------------------------------
-- Sync reports (every PC)
-- ---------------------------------------------------------------------------
Civ6Ai_OrderChannel._reportedTurn = Civ6Ai_OrderChannel._reportedTurn or -1
function Civ6Ai_OrderChannel.SendReport(turn)
  local shared = Civ6Ai_OrderChannel._Shared()
  local mine = shared.Checksums ~= nil and shared.Checksums[turn] or nil
  if mine == nil then
    log("report_skipped|turn=" .. tostring(turn) .. "|no_checksum")
    return false
  end
  Civ6Ai_OrderChannel._reportedTurn = turn
  return Civ6Ai_OrderChannel.Send(Civ6Ai_OrderChannel.K.REPORT,
    { T = turn, H = mine.sum, R = mine.orders, Q = mine.count }) ~= nil
end

function Civ6Ai_OrderChannel._ScheduleReport()
  local turn = Game.GetCurrentGameTurn()
  if Civ6Ai_OrderChannel._reportedTurn == turn or Civ6Ai_OrderChannel._reportScheduled == turn then
    return
  end
  Civ6Ai_OrderChannel._reportScheduled = turn
  local started = Civ6Ai_OrderChannel._Now()
  Civ6Ai_Util.ScheduleTick(function()
    if Game.GetCurrentGameTurn() ~= turn then
      return false
    end
    if Civ6Ai_OrderChannel._Now() - started < Civ6Ai_OrderChannel.REPORT_DELAY_SECONDS then
      return true
    end
    Civ6Ai_OrderChannel.SendReport(turn)
    return false
  end)
end

function Civ6Ai_OrderChannel._OnTurnBegin()
  if Civ6Ai_OrderChannel.IsActive() then
    Civ6Ai_OrderChannel._ScheduleReport()
  end
end

function Civ6Ai_OrderChannel.Initialize()
  if Civ6Ai_OrderChannel._initialized then
    return
  end
  Civ6Ai_OrderChannel._initialized = true
  if Events ~= nil and Events.LocalPlayerTurnBegin ~= nil then
    Events.LocalPlayerTurnBegin.Add(Civ6Ai_OrderChannel._OnTurnBegin)
  end
  log("ready|active=" .. tostring(Civ6Ai_OrderChannel.IsActive()) .. "|local=" .. tostring(Game.GetLocalPlayer()))
end
