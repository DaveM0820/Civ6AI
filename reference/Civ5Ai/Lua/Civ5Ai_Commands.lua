-- Single kind catalog: Snapshot emit prefixes, Apply handlers, Net tokens, parse salvage.
Civ5Ai_Commands = Civ5Ai_Commands or {}

Civ5Ai_Commands.CATALOG = {
  {
    kind = "adopt_social_policy",
    prefix = "CMD_policy_",
    net = "policy",
    shape = "policy",
    apply = "_AdoptSocialPolicy",
    mp = true,
    tier = "v1",
    description = "Adopt social policy or ideology tenet when culture allows",
  },
  {
    kind = "unlock_policy_branch",
    prefix = "CMD_branch_",
    net = "branch",
    shape = "branch",
    apply = "_UnlockPolicyBranch",
    mp = true,
    tier = "v1",
    description = "Unlock a policy branch when prerequisites are met",
  },
  {
    kind = "adopt_ideology",
    prefix = "CMD_ideology_",
    net = "ideology",
    shape = "branch",
    apply = "_AdoptIdeology",
    mp = true,
    tier = "v1",
    description = "Choose Freedom, Order, or Autocracy when eligible",
  },
  {
    kind = "set_research_tech",
    prefix = "CMD_research_",
    net = "research",
    shape = "tech",
    apply = "_SetResearchTech",
    mp = true,
    tier = "v1",
    description = "Set empire research technology",
  },
  {
    kind = "queue_production",
    prefix = "CMD_prod_",
    net = "prod",
    shape = "prod",
    apply = "_QueueProduction",
    mp = true,
    tier = "v1",
    description = "Queue city production (unit, building, project, or process)",
  },
  {
    kind = "buy_with_gold",
    prefix = "CMD_buy_gold_",
    net = "buygold",
    shape = "prod",
    apply = "_BuyWithGold",
    mp = true,
    tier = "v1",
    description = "Purchase unit or building with gold",
  },
  {
    kind = "buy_with_faith",
    prefix = "CMD_buy_faith_",
    net = "buyfaith",
    shape = "prod",
    apply = "_BuyWithFaith",
    mp = true,
    tier = "v1",
    description = "Purchase unit or building with faith",
  },
  {
    kind = "disband_unit",
    prefix = "CMD_disband_",
    net = "disband",
    shape = "unit",
    apply = "_DisbandUnit",
    mp = true,
    tier = "v1",
    description = "Disband a unit (vanilla delete; refunds some gold)",
  },
  {
    kind = "sell_building",
    prefix = "CMD_sellbldg_",
    net = "sellbldg",
    shape = "prod",
    apply = "_SellBuilding",
    mp = true,
    tier = "v1",
    description = "Sell a constructed city building for gold",
  },
  {
    kind = "set_city_status",
    prefix = "CMD_capture_",
    net = "capture",
    shape = "city_status",
    apply = "_SetCityStatus",
    mp = true,
    tier = "v1",
    description = "Puppet, annex, or raze a captured city",
  },
  {
    kind = "move_unit",
    prefix = "CMD_move_",
    net = "move",
    shape = "unit_xy",
    apply = "_MoveUnit",
    mp = true,
    tier = "v1",
    description = "Move unit to plot (open coordinates or injected)",
  },
  {
    kind = "attack_target",
    prefix = "CMD_attack_",
    net = "attack",
    shape = "unit_xy",
    apply = "_AttackTarget",
    mp = true,
    tier = "v1",
    description = "Attack plot with unit",
  },
  {
    kind = "range_attack",
    prefix = "CMD_range_",
    net = "range",
    shape = "unit_xy",
    apply = "_RangeAttack",
    mp = true,
    tier = "v1",
    description = "Range attack plot",
  },
  {
    kind = "city_range_strike",
    prefix = "CMD_city_range_",
    net = "cityrange",
    shape = "city_xy",
    apply = "_CityRangeStrike",
    mp = true,
    tier = "v1",
    description = "City bombard at range",
  },
  {
    kind = "found_city",
    prefix = "CMD_found_",
    net = "found",
    shape = "unit",
    apply = "_FoundCity",
    mp = true,
    tier = "v1",
    description = "Found city with settler",
  },
  {
    kind = "improve_tile",
    prefix = "CMD_improve_",
    net = "improve",
    shape = "unit_build",
    apply = "_ImproveTile",
    mp = true,
    tier = "v1",
    description = "Worker or work boat improves the unit's current plot",
  },
  {
    kind = "automate_unit",
    prefix = "CMD_automate_",
    net = "automate",
    shape = "unit_automate",
    apply = "_AutomateUnit",
    mp = true,
    tier = "v1",
    description = "Automate worker builds or scout exploration",
  },
  {
    kind = "discover_tech",
    prefix = "CMD_discover_",
    net = "discover",
    shape = "unit",
    apply = "_DiscoverTech",
    mp = true,
    tier = "v1",
    description = "Great scientist bulbs a technology",
  },
  {
    kind = "hurry_production",
    prefix = "CMD_hurry_",
    net = "hurry",
    shape = "unit",
    apply = "_HurryProduction",
    mp = true,
    tier = "v1",
    description = "Great engineer hurries city production",
  },
  {
    kind = "trade_mission",
    prefix = "CMD_trade_",
    net = "trade",
    shape = "unit",
    apply = "_TradeMission",
    mp = true,
    tier = "v1",
    description = "Great merchant trade mission on current plot",
  },
  {
    kind = "start_golden_age",
    prefix = "CMD_golden_",
    net = "golden",
    shape = "unit",
    apply = "_StartGoldenAge",
    mp = true,
    tier = "v1",
    description = "Great person starts a golden age",
  },
  {
    kind = "create_great_work",
    prefix = "CMD_greatwork_",
    net = "greatwork",
    shape = "unit",
    apply = "_CreateGreatWork",
    mp = true,
    tier = "v1",
    description = "Great artist or musician creates a great work",
  },
  {
    kind = "unit_posture_fortify",
    prefix = "CMD_fortify_",
    net = "fortify",
    shape = "unit",
    apply = "_UnitFortify",
    mp = true,
    tier = "v1",
    description = "Fortify unit",
  },
  {
    kind = "unit_posture_sleep",
    prefix = "CMD_sleep_",
    net = "sleep",
    shape = "unit",
    apply = "_UnitSleep",
    mp = true,
    tier = "v1",
    description = "Sleep unit",
  },
  {
    kind = "unit_posture_alert",
    prefix = "CMD_alert_",
    net = "alert",
    shape = "unit",
    apply = "_UnitAlert",
    mp = true,
    tier = "v1",
    description = "Alert unit",
  },
  {
    kind = "unit_posture_heal",
    prefix = "CMD_heal_",
    net = "heal",
    shape = "unit",
    apply = "_UnitHeal",
    mp = true,
    tier = "v1",
    description = "Heal unit",
  },
  {
    kind = "unit_skip",
    prefix = "CMD_skip_",
    net = "skip",
    shape = "unit",
    apply = "_UnitSkip",
    mp = true,
    tier = "v1",
    description = "Skip unit turn",
  },
  {
    kind = "promote_unit",
    prefix = "CMD_promote_",
    net = "promote",
    shape = "unit_promo",
    apply = "_PromoteUnit",
    mp = true,
    tier = "v1",
    description = "Choose unit promotion when XP threshold reached",
  },
  {
    kind = "rebase",
    prefix = "CMD_rebase_",
    net = "rebase",
    shape = "unit_xy",
    apply = "_Rebase",
    mp = true,
    tier = "v1",
    description = "Air unit rebase to a city or carrier",
  },
  {
    kind = "paradrop",
    prefix = "CMD_paradrop_",
    net = "paradrop",
    shape = "unit_xy",
    apply = "_Paradrop",
    mp = true,
    tier = "v1",
    description = "Paratrooper paradrop to a legal plot",
  },
  {
    kind = "nuke",
    prefix = "CMD_nuke_",
    net = "nuke",
    shape = "unit_xy",
    apply = "_Nuke",
    mp = true,
    tier = "v1",
    description = "Nuclear strike at a legal plot",
  },
  {
    kind = "air_patrol",
    prefix = "CMD_intercept_",
    net = "intercept",
    shape = "unit",
    apply = "_AirPatrol",
    mp = true,
    tier = "v1",
    description = "Fighter intercept from current base",
  },
  {
    kind = "spread_religion",
    prefix = "CMD_spread_",
    net = "spread",
    shape = "unit",
    apply = "_SpreadReligion",
    mp = true,
    tier = "v1",
    description = "Missionary spreads religion on the current city tile",
  },
  {
    kind = "remove_heresy",
    prefix = "CMD_heresy_",
    net = "heresy",
    shape = "unit",
    apply = "_RemoveHeresy",
    mp = true,
    tier = "v1",
    description = "Inquisitor removes heresy on the current city tile",
  },
  {
    kind = "pillage",
    prefix = "CMD_pillage_",
    net = "pillage",
    shape = "unit",
    apply = "_Pillage",
    mp = true,
    tier = "v1",
    description = "Pillage the improvement on the unit's current plot",
  },
  {
    kind = "upgrade_unit",
    prefix = "CMD_upgrade_",
    net = "upgrade",
    shape = "unit_type",
    apply = "_UpgradeUnit",
    mp = true,
    tier = "v1",
    description = "Upgrade unit when gold and tech allow",
  },
  {
    kind = "choose_maya_bonus",
    prefix = "CMD_maya_",
    net = "maya",
    shape = "maya",
    apply = "_ChooseMayaBonus",
    mp = true,
    tier = "v1",
    description = "Maya Long Count great person choice",
  },
  {
    kind = "choose_free_great_person",
    prefix = "CMD_freegp_",
    net = "freegp",
    shape = "maya",
    apply = "_ChooseFreeGreatPerson",
    mp = true,
    tier = "v1",
    description = "Choose a free Great Person reward",
  },
  {
    kind = "chat",
    prefix = "CMD_chat_",
    net = "chat",
    shape = "chat",
    apply = nil,
    mp = false,
    mp_via = "chat_encode",
    tier = "v1",
    description = "Send chat message (sidecar chat_messages, not apply commands)",
  },
  {
    kind = "propose_deal",
    prefix = "CMD_propose_",
    net = "dealpropose",
    shape = "deal_propose",
    apply = "ProposeDeal",
    apply_mod = "Civ5Ai_Diplo",
    mp = true,
    tier = "v1",
    description = "Propose a catalog diplomacy deal to another major civ",
  },
  {
    kind = "respond_to_deal",
    prefix = "CMD_accept_",
    aliases = { "CMD_reject_" },
    net = "dealrespond",
    shape = "deal_respond",
    apply = "RespondToDeal",
    apply_mod = "Civ5Ai_Diplo",
    mp = true,
    tier = "v1",
    description = "Accept or reject a pending trade proposal",
  },
  {
    kind = "cancel_deal",
    prefix = "CMD_cancel_",
    net = "canceldeal",
    shape = "deal_cancel",
    apply = "CancelDeal",
    apply_mod = "Civ5Ai_Diplo",
    mp = true,
    tier = "v1",
    description = "Cancel an active bilateral deal",
  },
  {
    kind = "declare_war",
    prefix = "CMD_declare_war_",
    net = "declarewar",
    shape = "war",
    apply = "DeclareWar",
    apply_mod = "Civ5Ai_Diplo",
    mp = true,
    tier = "v1",
    description = "Declare war on a met major this turn via Teams:DeclareWar",
  },
  {
    kind = "set_major_civ_approach",
    prefix = "CMD_approach_",
    net = "approach",
    shape = "approach",
    apply = "SetMajorCivApproach",
    apply_mod = "Civ5Ai_Diplo",
    mp = true,
    tier = "v1",
    description = "Set public major-civ approach toward a met rival",
  },
  {
    kind = "congress_propose",
    prefix = "CMD_congress_propose_",
    net = "congresspropose",
    shape = "congress_propose",
    apply = "Propose",
    apply_mod = "Civ5Ai_Congress",
    mp = true,
    tier = "v1",
    description = "Propose enact or repeal at World Congress",
  },
  {
    kind = "congress_vote",
    prefix = "CMD_congress_",
    net = "congressvote",
    shape = "congress_vote",
    apply = "Vote",
    apply_mod = "Civ5Ai_Congress",
    mp = true,
    tier = "v1",
    description = "Vote or abstain during World Congress session",
  },
  {
    kind = "found_pantheon",
    prefix = "CMD_pantheon_",
    net = "pantheon",
    shape = "belief",
    apply = "_FoundPantheon",
    mp = true,
    tier = "v1",
    description = "Found pantheon when faith threshold reached",
  },
  {
    kind = "found_religion",
    prefix = "CMD_founder_",
    net = "founder",
    shape = "belief",
    apply = "_FoundReligion",
    mp = true,
    tier = "v1",
    description = "Found religion with prophet and belief picker",
  },
  {
    kind = "enhance_religion",
    prefix = "CMD_enhancer_",
    net = "enhancer",
    shape = "belief",
    apply = "_EnhanceReligion",
    mp = true,
    tier = "v1",
    description = "Enhance religion with additional beliefs",
  },

  {
    kind = "establish_trade_route",
    prefix = "CMD_route_",
    net = "traderoute",
    shape = "trade_route",
    apply = "_EstablishTradeRoute",
    mp = true,
    tier = "v1",
    description = "Assign caravan or cargo ship to a legal trade route destination",
  },
  {
    kind = "change_trade_home_city",
    prefix = "CMD_tradehome_",
    net = "tradehome",
    shape = "trade_home",
    apply = "_ChangeTradeHomeCity",
    mp = true,
    tier = "v1",
    description = "Move caravan or cargo ship home/origin city",
  },
  {
    kind = "recall_trader",
    prefix = "CMD_recalltrade_",
    net = "recalltrade",
    shape = "unit",
    apply = "_RecallTrader",
    mp = true,
    tier = "v1",
    description = "Recall caravan or cargo ship from active trade route",
  },
}


Civ5Ai_Commands.DEFERRED = {
  -- establish_trade_route promoted to CATALOG (CIV5AI_TRADE_UNIT_COMMANDS_V1)
  { kind = "move_spy", phase = 5, description = "Assign spy to city" },
  { kind = "stage_coup", phase = 5, description = "Spy stages coup in foreign city" },
  { kind = "diplomacy_deal", phase = 7, description = "Structured diplomacy deal (gold, luxuries, war/peace)" },
}

function Civ5Ai_Commands._Index()
  if Civ5Ai_Commands._byKind ~= nil then
    return
  end
  Civ5Ai_Commands._byKind = {}
  Civ5Ai_Commands._byNet = {}
  Civ5Ai_Commands._prefixes = {}
  for _, row in ipairs(Civ5Ai_Commands.CATALOG) do
    Civ5Ai_Commands._byKind[row.kind] = row
    if row.net ~= nil and row.net ~= "chat" then
      Civ5Ai_Commands._byNet[row.net] = row
    end
    if row.prefix ~= nil then
      table.insert(Civ5Ai_Commands._prefixes, { prefix = row.prefix, kind = row.kind })
    end
    if row.aliases ~= nil then
      for _, alias in ipairs(row.aliases) do
        table.insert(Civ5Ai_Commands._prefixes, { prefix = alias, kind = row.kind })
      end
    end
  end
  table.sort(Civ5Ai_Commands._prefixes, function(a, b)
    return #a.prefix > #b.prefix
  end)
end

function Civ5Ai_Commands.ByKind(kind)
  Civ5Ai_Commands._Index()
  if kind == nil then
    return nil
  end
  return Civ5Ai_Commands._byKind[kind]
end

function Civ5Ai_Commands.KindFromCommandId(commandId)
  Civ5Ai_Commands._Index()
  if commandId == nil or commandId == "" then
    return nil
  end
  for _, row in ipairs(Civ5Ai_Commands._prefixes) do
    if string.sub(commandId, 1, #row.prefix) == row.prefix then
      return row.kind
    end
  end
  return nil
end

function Civ5Ai_Commands.MpKindSet()
  local set = {}
  for _, row in ipairs(Civ5Ai_Commands.CATALOG) do
    if row.mp == true then
      set[row.kind] = true
    end
  end
  return set
end

function Civ5Ai_Commands.Apply(playerID, command)
  local row = Civ5Ai_Commands.ByKind(command and command.kind)
  if row == nil or row.apply == nil then
    return false, "unsupported_kind"
  end
  local args = command.arguments or {}
  if row.apply_mod == "Civ5Ai_Diplo" then
    return Civ5Ai_Diplo[row.apply](playerID, args)
  end
  if row.apply_mod == "Civ5Ai_Congress" then
    return Civ5Ai_Congress[row.apply](playerID, args)
  end
  return Civ5Ai_Apply[row.apply](playerID, args)
end

function Civ5Ai_Commands._Arg(args, key)
  if args == nil then
    return nil
  end
  return args[key]
end

function Civ5Ai_Commands.EncodeNet(command)
  local row = Civ5Ai_Commands.ByKind(command and command.kind)
  if row == nil or row.net == nil or row.shape == "chat" then
    return nil
  end
  local args = command.arguments or {}
  local shape = row.shape
  local net = row.net
  if shape == "tech" and args.tech_id ~= nil then
    return net .. ":" .. tostring(args.tech_id)
  end
  if shape == "prod" and args.city_id ~= nil and args.build_id ~= nil then
    return net .. ":" .. tostring(args.city_id) .. ":" .. tostring(args.build_id)
  end
  if shape == "city_status" and args.city_id ~= nil and args.status ~= nil then
    return net .. ":" .. tostring(args.city_id) .. ":" .. tostring(args.status)
  end
  if shape == "unit" and args.unit_id ~= nil then
    return net .. ":" .. tostring(args.unit_id)
  end
  if shape == "unit_xy" and args.unit_id ~= nil then
    return net
      .. ":"
      .. tostring(args.unit_id)
      .. ":"
      .. tostring(args.target_x or args.plot_x or "")
      .. ":"
      .. tostring(args.target_y or args.plot_y or "")
  end
  if shape == "city_xy" and args.city_id ~= nil then
    return net
      .. ":"
      .. tostring(args.city_id)
      .. ":"
      .. tostring(args.target_x or args.plot_x or "")
      .. ":"
      .. tostring(args.target_y or args.plot_y or "")
  end
  if shape == "policy" and args.policy_id ~= nil then
    return net .. ":" .. tostring(args.policy_id)
  end
  if shape == "branch" and args.policy_branch_id ~= nil then
    return net .. ":" .. tostring(args.policy_branch_id)
  end
  if shape == "unit_build" and args.unit_id ~= nil and args.build_id ~= nil then
    return net .. ":" .. tostring(args.unit_id) .. ":" .. tostring(args.build_id)
  end
  if shape == "unit_automate" and args.unit_id ~= nil then
    return net .. ":" .. tostring(args.unit_id) .. ":" .. tostring(args.automate_id or args.data1_id or "")
  end
  if shape == "unit_type" and args.unit_id ~= nil then
    if args.unit_type_id ~= nil then
      return net .. ":" .. tostring(args.unit_id) .. ":" .. tostring(args.unit_type_id)
    end
    return net .. ":" .. tostring(args.unit_id)
  end
  if shape == "unit_promo" and args.unit_id ~= nil and args.promotion_id ~= nil then
    return net .. ":" .. tostring(args.unit_id) .. ":" .. tostring(args.promotion_id)
  end
  if shape == "maya" and args.unit_type_id ~= nil then
    return net .. ":" .. tostring(args.unit_type_id)
  end
  if shape == "belief" and args.belief_id ~= nil then
    return net .. ":" .. tostring(args.belief_id)
  end
  if shape == "deal_propose" and args.proposal_id ~= nil then
    return net .. ":" .. tostring(args.proposal_id)
  end
  if shape == "deal_respond" and args.request_id ~= nil and args.response_id ~= nil then
    return net .. ":" .. tostring(args.request_id) .. ":" .. tostring(args.response_id)
  end
  if shape == "deal_cancel" and args.deal_id ~= nil then
    return net .. ":" .. tostring(args.deal_id)
  end
  if shape == "war" and args.target_player_id ~= nil then
    return net .. ":" .. tostring(args.target_player_id)
  end
  if shape == "approach" and args.target_player_id ~= nil and args.approach_id ~= nil then
    return net .. ":" .. tostring(args.target_player_id) .. ":" .. tostring(args.approach_id)
  end
  if shape == "congress_propose" and args.action ~= nil then
    if args.action == "enact" and args.resolution_type ~= nil then
      return net
        .. ":enact:"
        .. tostring(args.resolution_type)
        .. ":"
        .. tostring(args.choice_id or -1)
    end
    if args.action == "repeal" and args.resolution_id ~= nil then
      return net .. ":repeal:" .. tostring(args.resolution_id)
    end
  end
  if shape == "congress_vote" and args.action ~= nil then
    if args.action == "abstain" then
      return net .. ":abstain:" .. tostring(args.votes or 1)
    end
    if args.direction ~= nil and args.resolution_id ~= nil then
      return net
        .. ":"
        .. tostring(args.direction)
        .. ":"
        .. tostring(args.resolution_id)
        .. ":"
        .. tostring(args.votes or 1)
        .. ":"
        .. tostring(args.choice_id or -1)
    end
  end
  if shape == "trade_route" and args.unit_id ~= nil then
    return net
      .. ":"
      .. tostring(args.unit_id)
      .. ":"
      .. tostring(args.target_x or "")
      .. ":"
      .. tostring(args.target_y or "")
      .. ":"
      .. tostring(args.trade_connection_type or "TRADE_CONNECTION_INTERNATIONAL")
  end
  if shape == "trade_home" and args.unit_id ~= nil then
    return net
      .. ":"
      .. tostring(args.unit_id)
      .. ":"
      .. tostring(args.target_x or "")
      .. ":"
      .. tostring(args.target_y or "")
  end
  return nil
end

function Civ5Ai_Commands.DecodeNet(token)
  Civ5Ai_Commands._Index()
  local net, rest = string.match(token or "", "^([^:]+):(.+)$")
  if net == nil then
    return nil
  end
  local row = Civ5Ai_Commands._byNet[net]
  if row == nil then
    return nil
  end
  local shape = row.shape
  local command = { kind = row.kind, command_id = "", arguments = {} }
  local args = command.arguments
  if shape == "tech" then
    args.tech_id = rest
  elseif shape == "prod" then
    local cityId, buildId = string.match(rest, "^([^:]+):(.+)$")
    if cityId == nil then
      return nil
    end
    args.city_id = cityId
    args.build_id = buildId
  elseif shape == "city_status" then
    local cityId, status = string.match(rest, "^([^:]+):(.+)$")
    if cityId == nil then
      return nil
    end
    args.city_id = cityId
    args.status = status
  elseif shape == "unit" then
    args.unit_id = rest
  elseif shape == "unit_xy" then
    local unitId, x, y = string.match(rest, "^([^:]+):([^:]+):(.+)$")
    if unitId == nil then
      return nil
    end
    args.unit_id = unitId
    args.target_x = tonumber(x)
    args.target_y = tonumber(y)
  elseif shape == "city_xy" then
    local cityId, x, y = string.match(rest, "^([^:]+):([^:]+):(.+)$")
    if cityId == nil then
      return nil
    end
    args.city_id = cityId
    args.target_x = tonumber(x)
    args.target_y = tonumber(y)
  elseif shape == "policy" then
    args.policy_id = rest
  elseif shape == "branch" then
    args.policy_branch_id = rest
  elseif shape == "unit_build" then
    local unitId, buildId = string.match(rest, "^([^:]+):(.+)$")
    if unitId == nil then
      return nil
    end
    args.unit_id = unitId
    args.build_id = buildId
  elseif shape == "unit_automate" then
    local unitId, automateId = string.match(rest, "^([^:]+):(.+)$")
    if unitId == nil then
      return nil
    end
    args.unit_id = unitId
    args.automate_id = automateId
  elseif shape == "unit_type" then
    local unitId, typeId = string.match(rest, "^([^:]+):(.+)$")
    if unitId == nil then
      args.unit_id = rest
    else
      args.unit_id = unitId
      args.unit_type_id = typeId
    end
  elseif shape == "unit_promo" then
    local unitId, promotionId = string.match(rest, "^([^:]+):(.+)$")
    if unitId == nil then
      return nil
    end
    args.unit_id = unitId
    args.promotion_id = promotionId
  elseif shape == "maya" then
    args.unit_type_id = rest
  elseif shape == "belief" then
    args.belief_id = rest
  elseif shape == "deal_propose" then
    args.proposal_id = rest
  elseif shape == "deal_respond" then
    local requestId, responseId = string.match(rest, "^([^:]+):(.+)$")
    if requestId == nil then
      return nil
    end
    args.request_id = requestId
    args.response_id = responseId
  elseif shape == "deal_cancel" then
    args.deal_id = rest
  elseif shape == "war" then
    args.target_player_id = rest
  elseif shape == "approach" then
    local targetId, approachId = string.match(rest, "^([^:]+):(.+)$")
    if targetId == nil then
      return nil
    end
    args.target_player_id = targetId
    args.approach_id = approachId
  elseif shape == "congress_propose" then
    local action, resolutionType, choiceId = string.match(rest, "^([^:]+):([^:]+):(.+)$")
    local repealId = string.match(rest, "^repeal:(.+)$")
    if repealId ~= nil then
      args.action = "repeal"
      args.resolution_id = tonumber(repealId)
    elseif action == "enact" and resolutionType ~= nil then
      args.action = "enact"
      args.resolution_type = resolutionType
      args.choice_id = tonumber(choiceId)
    else
      return nil
    end
  elseif shape == "congress_vote" then
    local abstainVotes = string.match(rest, "^abstain:(.+)$")
    if abstainVotes ~= nil then
      args.action = "abstain"
      args.votes = tonumber(abstainVotes)
    else
      local direction, resolutionId, votes, choiceId = string.match(rest, "^([^:]+):([^:]+):([^:]+):(.+)$")
      if direction == nil then
        return nil
      end
      args.action = "vote"
      args.direction = direction
      args.resolution_id = tonumber(resolutionId)
      args.votes = tonumber(votes)
      args.choice_id = tonumber(choiceId)
    end
  elseif shape == "trade_route" then
    local unitId, x, y, connType = string.match(rest, "^([^:]+):([^:]+):([^:]+):(.+)$")
    if unitId == nil then
      return nil
    end
    args.unit_id = unitId
    args.target_x = tonumber(x)
    args.target_y = tonumber(y)
    args.trade_connection_type = connType
  elseif shape == "trade_home" then
    local unitId, x, y = string.match(rest, "^([^:]+):([^:]+):(.+)$")
    if unitId == nil then
      return nil
    end
    args.unit_id = unitId
    args.target_x = tonumber(x)
    args.target_y = tonumber(y)
  else
    return nil
  end
  return command
end
