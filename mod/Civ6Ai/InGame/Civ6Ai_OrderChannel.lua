-- Civ6Ai order channel (interface side). Every model order for a seat other
-- than the local one goes out as a synced EXECUTE_SCRIPT player operation,
-- handled on every PC by Gameplay/Civ6Ai_Orders.lua, in network games and
-- single player alike. This file never changes game state itself.
--
-- Host: SendDecision turns a model decision into one batch of orders for the
-- seat's next turn, keeps seq -> command locally, and writes each command's
-- real result to apply-results.jsonl once the gameplay side has played it
-- (at that seat's turn start).
-- Every PC in a network game: a few seconds into each turn it reports its own
-- checksum for the turn, so the host's log shows whether the other PCs still
-- match.
Civ6Ai_OrderChannel = Civ6Ai_OrderChannel or {}

Civ6Ai_OrderChannel.K = {
  MOVE = 1, RESEARCH = 2, CIVIC = 3, FOUND = 4, SKIP = 5, FORTIFY = 6, ATTACK = 7, PRIORITY = 9,
  GOVERNMENT = 10, POLICY = 11, PANTHEON = 12, RELIGION = 13, GP_RECRUIT = 14, GP_PATRONIZE = 15, GOVERNOR = 16,
  WAR = 17, PEACE = 18, BUY = 19, BUY_TILE = 20, IMPROVE = 21, PILLAGE = 22,
  FINISH_SEAT = 23,
  REPORT = 30, PING = 40, TEST_MODE = 49, TEST_INTROSPECT = 50, TEST_SPAWN_ENEMY = 51,
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
  send_diplomatic_action = 17, propose_peace = 18, purchase_item = 19, purchase_tile = 20,
  worker_improve = 21, pillage_improvement = 22,
}
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

function Civ6Ai_OrderChannel._PlayerNum(id)
  if type(id) == "number" then
    return id
  end
  local n = string.match(tostring(id or ""), "PLAYER_(%d+)")
  if n ~= nil then
    return tonumber(n)
  end
  return tonumber(id)
end

function Civ6Ai_OrderChannel._CityNum(id)
  local n = tonumber((tostring(id or "")):match("CITY_(%d+)"))
  if n ~= nil then
    return n % 65536
  end
  return tonumber(id)
end

function Civ6Ai_OrderChannel._WarAction(action)
  local text = string.upper(tostring(action or ""))
  text = string.gsub(text, "%s+", "_")
  if text == "DECLARE_SURPRISE_WAR" or text == "SURPRISE_WAR" then
    return 1
  end
  if text == "DECLARE_WAR" or text == "DECLARE_FORMAL_WAR" or text == "FORMAL_WAR" or text == "WAR" then
    return 0
  end
  return nil
end

-- Integer fields for one model command, or nil, reason when it has no synced
-- route.
function Civ6Ai_OrderChannel._Fields(playerID, command)
  local kind = Civ6Ai_OrderChannel.KIND_BY_COMMAND[command.kind or ""]
  if kind == nil then
    if command.kind == "queue_production" then
      return nil, "production_requires_local_player"
    end
    if command.kind == "appoint_governor" or command.kind == "assign_governor" or command.kind == "promote_governor" then
      return nil, "governors cannot be set for this seat by a game script (no gameplay route); "
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
    f.X, f.Y, f.V, f.W = b[1] or -1, b[2] or -1, b[3] or -1, b[4] or -1
    f.U = f.U or -1
  elseif kind == 14 or kind == 15 then
    local row = args.individual_id ~= nil and GameInfo.GreatPersonIndividuals[args.individual_id] or nil
    if row == nil then
      return nil, "unknown great person " .. tostring(args.individual_id)
    end
    f.I = row.Index
    f.X = string.lower(tostring(args.yield or "gold")) == "faith" and 1 or 0
  elseif kind == 17 then
    local other = Civ6Ai_OrderChannel._PlayerNum(args.target_player_id)
    local war = Civ6Ai_OrderChannel._WarAction(args.action_id)
    if other == nil then
      return nil, "missing_target_player"
    end
    if war == nil then
      return nil, "only DECLARE_WAR can be sent on the order channel"
    end
    f.I, f.X = other, war
  elseif kind == 18 then
    local other = Civ6Ai_OrderChannel._PlayerNum(args.target_player_id)
    if other == nil then
      return nil, "missing_target_player"
    end
    f.I = other
  elseif kind == 19 then
    local cityNum = Civ6Ai_OrderChannel._CityNum(args.city_id)
    local item = args.item_id
    local unitRow = item ~= nil and GameInfo.Units ~= nil and GameInfo.Units[item] or nil
    local bldRow = item ~= nil and GameInfo.Buildings ~= nil and GameInfo.Buildings[item] or nil
    if cityNum == nil then
      return nil, "missing_city_id"
    end
    if unitRow == nil and bldRow == nil then
      return nil, item == nil and "missing_item_id" or ("unknown item " .. tostring(item))
    end
    f.X = cityNum
    f.I = (unitRow or bldRow).Index
    f.U = bldRow ~= nil and 1 or 0
    f.Y = string.lower(tostring(args.yield or "gold")) == "faith" and 1 or 0
  elseif kind == 20 then
    local cityNum = Civ6Ai_OrderChannel._CityNum(args.city_id)
    local x, y = Civ6Ai_Apply._ResolveTargetCoords(args)
    if cityNum == nil or x == nil or y == nil then
      return nil, "missing_city_or_tile"
    end
    f.I, f.X, f.Y = cityNum, x, y
  elseif kind == 21 then
    local row = args.improvement_id ~= nil and GameInfo.Improvements ~= nil
      and GameInfo.Improvements[args.improvement_id] or nil
    if f.U == nil or row == nil then
      return nil, args.improvement_id == nil and "missing_unit_or_improvement"
        or ("unknown improvement " .. tostring(args.improvement_id))
    end
    f.I = row.Index
    local x, y = Civ6Ai_Apply._ResolveTargetCoords(args)
    f.X, f.Y = x or -1, y or -1
  elseif kind == 22 then
    if f.U == nil then
      return nil, "missing_unit_id"
    end
    local x, y = Civ6Ai_Apply._ResolveTargetCoords(args)
    f.X, f.Y = x or -1, y or -1
  elseif f.U == nil then
    return nil, "missing_unit_id"
  end
  return f, ""
end

-- Send a whole model decision for one seat as one batch of orders for turn
-- forTurn. Returns the number of orders sent.
function Civ6Ai_OrderChannel.SendDecision(playerID, decision, forTurn)
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
  for j, entry in ipairs(orders) do
    local f = entry.fields
    f.B, f.J, f.N = batch, j, #orders
    local kind = f.K
    f.K = nil
    local seq = Civ6Ai_OrderChannel.Send(kind, f, forTurn)
    if seq ~= nil then
      Civ6Ai_OrderChannel._pending[seq] = { playerID = playerID, command = entry.command, turn = forTurn }
      sent = sent + 1
    else
      Civ6Ai_Apply._RecordResult(playerID, entry.command, false, "send_failed", entry.command.arguments or {})
    end
  end
  Civ6Ai_OrderChannel._EnsureResultPump()
  return sent
end

-- ---------------------------------------------------------------------------
-- Results
-- ---------------------------------------------------------------------------
-- A sent order's result comes back when the gameplay side plays it (at the
-- seat's turn start) or refuses it. An order still without a result once its
-- turn is over never ran.
function Civ6Ai_OrderChannel.DrainResults()
  local shared = Civ6Ai_OrderChannel._Shared()
  local me = Game.GetLocalPlayer()
  for _, r in ipairs(shared.OrderResults or {}) do
    local entry = r.sender == me and Civ6Ai_OrderChannel._pending[r.seq] or nil
    if entry ~= nil then
      Civ6Ai_OrderChannel._pending[r.seq] = nil
      Civ6Ai_Apply._RecordResult(entry.playerID, entry.command, r.ok == true, r.reason, entry.command.arguments or {})
    end
  end
  local turn = Game.GetCurrentGameTurn()
  local left = 0
  for seq, entry in pairs(Civ6Ai_OrderChannel._pending) do
    if turn > entry.turn then
      Civ6Ai_OrderChannel._pending[seq] = nil
      Civ6Ai_Apply._RecordResult(entry.playerID, entry.command, false, "no_result_from_gameplay", entry.command.arguments or {})
      log("result_missing|seq=" .. tostring(seq) .. "|for_turn=" .. tostring(entry.turn))
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
  if Civ6Ai_Config.IsNetworkGame() then
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
  log("ready|network=" .. tostring(Civ6Ai_Config.IsNetworkGame()) .. "|local=" .. tostring(Game.GetLocalPlayer()))
end
