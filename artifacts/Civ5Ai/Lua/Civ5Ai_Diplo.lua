-- Civ5Ai diplomacy: async deals via CP m_ProposedDeals + net tokens.
Civ5Ai_Diplo = Civ5Ai_Diplo or {}

Civ5Ai_Diplo._CATALOG = {
  { kind = "EMBASSY", label = "embassy", requires_war = false, requires_peace = true },
  { kind = "OPEN_BORDERS", label = "open_borders", requires_war = false, requires_peace = true },
  { kind = "DOF", label = "declaration_of_friendship", requires_war = false, requires_peace = true },
  { kind = "RESEARCH_AGREEMENT", label = "research_agreement", requires_war = false, requires_peace = true },
  { kind = "DEFENSIVE_PACT", label = "defensive_pact", requires_war = false, requires_peace = true },
  { kind = "PEACE", label = "peace_treaty", requires_war = true, requires_peace = false },
}

Civ5Ai_Diplo._MAX_PROPOSALS = 128

function Civ5Ai_Diplo._DllReady()
  return Game ~= nil and Game.Civ5AiQueueCatalogDeal ~= nil
end

function Civ5Ai_Diplo._TradeItemKind(itemType)
  if TradeableItems == nil then
    return "TRADE_UNKNOWN"
  end
  for name, value in pairs(TradeableItems) do
    if value == itemType then
      return string.gsub(name, "^TRADE_ITEM_", "")
    end
  end
  return "TRADE_" .. tostring(itemType)
end

function Civ5Ai_Diplo._ResourceType(data1)
  if data1 == nil or data1 < 0 then
    return nil
  end
  local row = GameInfo.Resources[data1]
  if row ~= nil then
    return row.Type
  end
  return nil
end

function Civ5Ai_Diplo._DealItemsForPlayer(deal, playerID)
  local items = {}
  if deal == nil or deal.ResetIterator == nil then
    return items
  end
  deal:ResetIterator()
  while true do
    local itemType, duration, finalTurn, data1, data2, data3, flag1, fromPlayer =
      deal:GetNextItem()
    if itemType == nil then
      break
    end
    if fromPlayer == playerID then
      local kind = Civ5Ai_Diplo._TradeItemKind(itemType)
      local row = {
        kind = kind,
        trade_item_id = "TRADE_ITEM_" .. kind,
        data_id = Civ5Ai_Util.JsonNull(),
        amount = Civ5Ai_Util.JsonNull(),
        denial_id = Civ5Ai_Util.JsonNull(),
      }
      if kind == "RESOURCES" then
        row.data_id = Civ5Ai_Diplo._ResourceType(data1) or Civ5Ai_Util.JsonNull()
        row.amount = data2 or Civ5Ai_Util.JsonNull()
      elseif kind == "GOLD" or kind == "GOLD_PER_TURN" then
        row.amount = data1 or Civ5Ai_Util.JsonNull()
      elseif kind == "TECHS" then
        local techRow = GameInfo.Technologies[data1]
        row.data_id = techRow and techRow.Type or Civ5Ai_Util.JsonNull()
      elseif kind == "CITIES" then
        row.data_id = "CITY_" .. tostring(data1)
      end
      table.insert(items, row)
    end
  end
  return items
end

function Civ5Ai_Diplo._RequestId(recipientID, senderID)
  return "DIPLO_TRADE_" .. tostring(recipientID) .. "_" .. tostring(senderID)
end

function Civ5Ai_Diplo._DiscussionFollowupKey(senderID, recipientID)
  return tostring(senderID) .. "_" .. tostring(recipientID)
end

function Civ5Ai_Diplo._DiscussionCatalogKind(diploUIState)
  if DiploUIStateTypes == nil or diploUIState == nil then
    return nil
  end
  if diploUIState == DiploUIStateTypes.DIPLO_UI_STATE_DISCUSS_WORK_WITH_US then
    return "DOF"
  end
  if diploUIState == DiploUIStateTypes.DIPLO_UI_STATE_DISCUSS_PLAN_RESEARCH_AGREEMENT then
    return "RESEARCH_AGREEMENT"
  end
  return nil
end

function Civ5Ai_Diplo._HasPendingFrom(senderID, recipientID)
  local want = Civ5Ai_Diplo._RequestId(recipientID, senderID)
  for _, row in ipairs(Civ5Ai_Diplo.BuildPendingRequests(recipientID)) do
    if row.request_id == want then
      return true
    end
  end
  return false
end

function Civ5Ai_Diplo._PendingRequestKind(deal)
  if deal == nil or deal.ResetIterator == nil then
    return "DIPLO_COMMENT_TRADING"
  end
  deal:ResetIterator()
  while true do
    local itemType = deal:GetNextItem()
    if itemType == nil then
      break
    end
    local kind = Civ5Ai_Diplo._TradeItemKind(itemType)
    if kind == "DECLARATION_OF_FRIENDSHIP" then
      return "DIPLO_COMMENT_DECLARATION_OF_FRIENDSHIP"
    end
    if kind == "EMBASSY" then
      return "DIPLO_COMMENT_EMBASSY"
    end
    if kind == "OPEN_BORDERS" then
      return "DIPLO_COMMENT_OPEN_BORDERS"
    end
    if kind == "RESEARCH_AGREEMENT" then
      return "DIPLO_COMMENT_RESEARCH_AGREEMENT"
    end
    if kind == "DEFENSIVE_PACT" then
      return "DIPLO_COMMENT_DEFENSIVE_PACT"
    end
  end
  return "DIPLO_COMMENT_TRADING"
end

function Civ5Ai_Diplo._QueueDofScratchDeal(fromID, toID)
  if UI == nil or UI.GetScratchDeal == nil then
    return false
  end
  local deal = UI.GetScratchDeal()
  if deal == nil or deal.ClearItems == nil or deal.AddDeclarationOfFriendship == nil then
    return false
  end
  deal:ClearItems()
  deal:SetFromPlayer(fromID)
  deal:SetToPlayer(toID)
  deal:AddDeclarationOfFriendship(fromID)
  deal:AddDeclarationOfFriendship(toID)
  return Civ5Ai_Diplo.QueueScratchProposal(fromID, toID)
end

function Civ5Ai_Diplo.QueueDiscussionProposal(recipientID, senderID, diploUIState, diploData)
  if not Civ5Ai_Diplo._ShouldDeferTradeUi(recipientID) then
    return false
  end
  local catalogKind = Civ5Ai_Diplo._DiscussionCatalogKind(diploUIState)
  if catalogKind == nil then
    return false
  end
  if Civ5Ai_Diplo._HasPendingFrom(senderID, recipientID) then
    Civ5Ai_Diplo._discussionFollowups = Civ5Ai_Diplo._discussionFollowups or {}
    Civ5Ai_Diplo._discussionFollowups[Civ5Ai_Diplo._DiscussionFollowupKey(senderID, recipientID)] = {
      state = diploUIState,
      data = diploData or 0,
    }
    return true
  end
  local queued = false
  if Civ5Ai_Diplo._DllReady() and Game.Civ5AiQueueCatalogDeal ~= nil then
    queued = Game.Civ5AiQueueCatalogDeal(senderID, recipientID, catalogKind) == true
  end
  if not queued and catalogKind == "DOF" then
    queued = Civ5Ai_Diplo._QueueDofScratchDeal(senderID, recipientID)
  end
  if not queued then
    return false
  end
  Civ5Ai_Diplo._discussionFollowups = Civ5Ai_Diplo._discussionFollowups or {}
  Civ5Ai_Diplo._discussionFollowups[Civ5Ai_Diplo._DiscussionFollowupKey(senderID, recipientID)] = {
    state = diploUIState,
    data = diploData or 0,
  }
  Civ5Ai_Util.Log(
    "diplo|queue_discussion|from="
      .. tostring(senderID)
      .. "|to="
      .. tostring(recipientID)
      .. "|kind="
      .. tostring(catalogKind)
      .. "|state="
      .. tostring(diploUIState)
  )
  return true
end

function Civ5Ai_Diplo._CompleteDiscussionFollowup(senderID, recipientID, accepted)
  Civ5Ai_Diplo._discussionFollowups = Civ5Ai_Diplo._discussionFollowups or {}
  local key = Civ5Ai_Diplo._DiscussionFollowupKey(senderID, recipientID)
  local entry = Civ5Ai_Diplo._discussionFollowups[key]
  if entry == nil then
    return
  end
  Civ5Ai_Diplo._discussionFollowups[key] = nil
  if Game == nil or Game.DoFromUIDiploEvent == nil or FromUIDiploEventTypes == nil or DiploUIStateTypes == nil then
    return
  end
  local buttonID = accepted and 1 or 2
  local state = entry.state
  if state == DiploUIStateTypes.DIPLO_UI_STATE_DISCUSS_WORK_WITH_US then
    Game.DoFromUIDiploEvent(
      FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_WORK_WITH_US_RESPONSE,
      senderID,
      buttonID,
      0
    )
  elseif state == DiploUIStateTypes.DIPLO_UI_STATE_DISCUSS_PLAN_RESEARCH_AGREEMENT then
    Game.DoFromUIDiploEvent(
      FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_PLAN_RA_RESPONSE,
      senderID,
      buttonID,
      0
    )
  end
  Civ5Ai_Util.Log(
    "diplo|discussion_followup|from="
      .. tostring(senderID)
      .. "|to="
      .. tostring(recipientID)
      .. "|accepted="
      .. tostring(accepted and 1 or 0)
      .. "|state="
      .. tostring(state)
  )
end

function Civ5Ai_Diplo._ProposalId(catalogKind, targetID)
  return "PROPOSAL_" .. tostring(catalogKind) .. "_" .. Civ5Ai_Util.PlayerId(targetID)
end

function Civ5Ai_Diplo._ParseProposalId(proposalId)
  local kind, target = string.match(proposalId, "^PROPOSAL_(.+)_PLAYER_(%d+)$")
  if kind == nil then
    return nil, nil
  end
  return kind, tonumber(target)
end

function Civ5Ai_Diplo._ParseRequestId(requestId)
  local recipient, sender = string.match(requestId, "^DIPLO_TRADE_(%d+)_(%d+)$")
  if recipient == nil then
    return nil, nil
  end
  return tonumber(recipient), tonumber(sender)
end

function Civ5Ai_Diplo._MetMajor(playerID, otherID)
  local us = Players[playerID]
  local other = Players[otherID]
  if us == nil or other == nil then
    return false
  end
  if not other:IsAlive() or other:IsBarbarian() or other:IsMinorCiv() then
    return false
  end
  return Teams[us:GetTeam()]:IsHasMet(other:GetTeam())
end

function Civ5Ai_Diplo._CatalogEntryForKind(kindToken)
  for _, row in ipairs(Civ5Ai_Diplo._CATALOG) do
    if row.kind == kindToken or row.label == kindToken then
      return row
    end
  end
  return nil
end

function Civ5Ai_Diplo._CanOfferCatalog(playerID, targetID, catalogRow)
  if not Civ5Ai_Diplo._DllReady() then
    return false
  end
  if not Civ5Ai_Diplo._MetMajor(playerID, targetID) then
    return false
  end
  local usTeam = Teams[Players[playerID]:GetTeam()]
  local themTeam = Teams[Players[targetID]:GetTeam()]
  local atWar = usTeam:IsAtWar(Players[targetID]:GetTeam()) == true
  if catalogRow.requires_war and not atWar then
    return false
  end
  if catalogRow.requires_peace and atWar then
    return false
  end
  return Game.Civ5AiCanQueueCatalogDeal(playerID, targetID, catalogRow.kind) == true
end

function Civ5Ai_Diplo._ApproachWireName(approach)
  if MajorCivApproachTypes == nil then
    if approach == 6 then
      return "FRIENDLY"
    elseif approach == 0 or approach == 1 then
      return "HOSTILE"
    elseif approach == 2 or approach == 3 then
      return "GUARDED"
    elseif approach == 4 then
      return "AFRAID"
    elseif approach == 5 then
      return "NEUTRAL"
    end
    return "UNKNOWN"
  end
  if approach == MajorCivApproachTypes.MAJOR_CIV_APPROACH_WAR then
    return "WAR"
  elseif approach == MajorCivApproachTypes.MAJOR_CIV_APPROACH_HOSTILE then
    return "HOSTILE"
  elseif approach == MajorCivApproachTypes.MAJOR_CIV_APPROACH_GUARDED
      or approach == MajorCivApproachTypes.MAJOR_CIV_APPROACH_DECEPTIVE then
    return "GUARDED"
  elseif approach == MajorCivApproachTypes.MAJOR_CIV_APPROACH_AFRAID then
    return "AFRAID"
  elseif approach == MajorCivApproachTypes.MAJOR_CIV_APPROACH_FRIENDLY then
    return "FRIENDLY"
  elseif approach == MajorCivApproachTypes.MAJOR_CIV_APPROACH_NEUTRAL then
    return "NEUTRAL"
  end
  return "UNKNOWN"
end

function Civ5Ai_Diplo._ApproachTypeFromWire(approachId)
  if approachId == nil or approachId == "" or MajorCivApproachTypes == nil then
    return nil
  end
  local key = "MAJOR_CIV_APPROACH_" .. tostring(approachId)
  return MajorCivApproachTypes[key]
end

function Civ5Ai_Diplo._AttitudeFor(player, otherID)
  local approach = 0
  if player ~= nil and player.GetMajorCivApproach ~= nil then
    approach = player:GetMajorCivApproach(otherID) or 0
  end
  local attitudeId = "ATTITUDE_CAUTIOUS"
  if MajorCivApproachTypes ~= nil then
    if approach == MajorCivApproachTypes.MAJOR_CIV_APPROACH_FRIENDLY then
      attitudeId = "ATTITUDE_FRIENDLY"
    elseif approach == MajorCivApproachTypes.MAJOR_CIV_APPROACH_HOSTILE
        or approach == MajorCivApproachTypes.MAJOR_CIV_APPROACH_WAR then
      attitudeId = "ATTITUDE_FURIOUS"
    elseif approach == MajorCivApproachTypes.MAJOR_CIV_APPROACH_GUARDED
        or approach == MajorCivApproachTypes.MAJOR_CIV_APPROACH_DECEPTIVE then
      attitudeId = "ATTITUDE_ANNOYED"
    elseif approach == MajorCivApproachTypes.MAJOR_CIV_APPROACH_AFRAID
        or approach == MajorCivApproachTypes.MAJOR_CIV_APPROACH_NEUTRAL then
      attitudeId = "ATTITUDE_CAUTIOUS"
    end
  else
    if approach == 6 then
      attitudeId = "ATTITUDE_FRIENDLY"
    elseif approach == 0 or approach == 1 then
      attitudeId = "ATTITUDE_FURIOUS"
    elseif approach == 2 or approach == 3 then
      attitudeId = "ATTITUDE_ANNOYED"
    end
  end
  return attitudeId, approach
end

function Civ5Ai_Diplo.RelationBetween(playerID, otherID)
  local us = Players[playerID]
  local other = Players[otherID]
  if us == nil or other == nil then
    return {
      met = false,
      at_war = false,
      open_borders = false,
      defensive_pact = false,
      vassal = false,
      attitude_id = "ATTITUDE_CAUTIOUS",
      attitude_value = 0,
    }
  end
  local ourTeam = Teams[us:GetTeam()]
  local theirTeam = Teams[other:GetTeam()]
  if ourTeam == nil or theirTeam == nil then
    return {
      met = false,
      at_war = false,
      open_borders = false,
      defensive_pact = false,
      vassal = false,
      attitude_id = "ATTITUDE_CAUTIOUS",
      attitude_value = 0,
    }
  end
  local attitudeId, approach = Civ5Ai_Diplo._AttitudeFor(us, otherID)
  local vassal = false
  if theirTeam ~= nil and theirTeam.IsVassal ~= nil then
    vassal = theirTeam:IsVassal(us:GetTeam()) == true
  end
  return {
    met = ourTeam:IsHasMet(other:GetTeam()),
    at_war = ourTeam:IsAtWar(other:GetTeam()) == true,
    open_borders = theirTeam:IsAllowsOpenBordersToTeam(us:GetTeam()),
    defensive_pact = ourTeam:IsDefensivePact(other:GetTeam()),
    vassal = vassal,
    attitude_id = attitudeId,
    attitude_value = approach,
    approach_id = Civ5Ai_Diplo._ApproachWireName(approach),
  }
end

function Civ5Ai_Diplo.SetMajorCivApproach(playerID, args)
  local targetToken = args and args.target_player_id
  local approachId = args and args.approach_id
  if targetToken == nil or approachId == nil or approachId == "" then
    return false, "missing_approach_args"
  end
  local targetID = Civ5Ai_Diplo._ParsePlayerId(targetToken)
  if targetID == nil or targetID < 0 then
    return false, "invalid_target_player"
  end
  local player = Players[playerID]
  local other = Players[targetID]
  if player == nil or other == nil or not other:IsAlive() then
    return false, "target_not_alive"
  end
  local approachType = Civ5Ai_Diplo._ApproachTypeFromWire(approachId)
  if approachType == nil then
    return false, "invalid_approach"
  end
  if player.SetMajorCivApproach == nil then
    return false, "set_approach_missing"
  end
  player:SetMajorCivApproach(targetID, approachType, false)
  return true, ""
end

function Civ5Ai_Diplo.BuildRelations(playerID)
  local relations = Civ5Ai_Util.JsonArrayList()
  local lastMajor = 21
  if GameDefines ~= nil and GameDefines.MAX_MAJOR_CIVS ~= nil then
    lastMajor = GameDefines.MAX_MAJOR_CIVS - 1
  end
  for otherID = 0, lastMajor do
    if otherID ~= playerID and Civ5Ai_Diplo._MetMajor(playerID, otherID) then
      table.insert(relations, {
        player_id = Civ5Ai_Util.PlayerId(otherID),
        relation = Civ5Ai_Diplo.RelationBetween(playerID, otherID),
      })
    end
  end
  return relations
end


-- DEAL_WIRE_CLEAR_V1: alias available proposals into legal_trade_inventory
-- (docs/civ5-diplomacy-trade.md). Soft surplus resources are mirrored on the
-- Python wire from your_empire.resources; engine still applies catalog deals only.
function Civ5Ai_Diplo.BuildLegalTradeInventory(playerID)
  local inventory = Civ5Ai_Util.JsonArrayList()
  local proposals = Civ5Ai_Diplo.BuildAvailableProposals(playerID)
  for _, proposal in ipairs(proposals) do
    local kindToken = Civ5Ai_Diplo._ParseProposalId(proposal.proposal_id)
    table.insert(inventory, {
      trade_item_id = "TRADE_ITEM_" .. tostring(kindToken or "UNKNOWN"),
      kind = tostring(kindToken or "UNKNOWN"),
      proposal_id = proposal.proposal_id,
      target_player_id = proposal.target_player_id,
      direction = "offer_or_request",
      amount = Civ5Ai_Util.JsonNull(),
      data_id = Civ5Ai_Util.JsonNull(),
    })
  end
  return inventory
end

function Civ5Ai_Diplo.BuildAvailableProposals(playerID)
  local proposals = Civ5Ai_Util.JsonArrayList()
  if not Civ5Ai_Diplo._DllReady() then
    return proposals
  end
  local lastMajor = 21
  if GameDefines ~= nil and GameDefines.MAX_MAJOR_CIVS ~= nil then
    lastMajor = GameDefines.MAX_MAJOR_CIVS - 1
  end
  for targetID = 0, lastMajor do
    if targetID ~= playerID then
      for _, catalogRow in ipairs(Civ5Ai_Diplo._CATALOG) do
        if Civ5Ai_Diplo._CanOfferCatalog(playerID, targetID, catalogRow) then
          table.insert(proposals, {
            proposal_id = Civ5Ai_Diplo._ProposalId(catalogRow.kind, targetID),
            target_player_id = Civ5Ai_Util.PlayerId(targetID),
            proposal_index = #proposals,
          })
          if #proposals >= Civ5Ai_Diplo._MAX_PROPOSALS then
            return proposals
          end
        end
      end
    end
  end
  return proposals
end

function Civ5Ai_Diplo.BuildPendingRequests(playerID)
  local pending = Civ5Ai_Util.JsonArrayList()
  if not Civ5Ai_Diplo._DllReady() or Game.GetCiv5AiNumProposedDeals == nil then
    return pending
  end
  local count = Game.GetCiv5AiNumProposedDeals(playerID) or 0
  for index = 0, count - 1 do
    local fromID, toID = Game.GetCiv5AiProposedDealPair(playerID, index)
    if toID == playerID and fromID ~= nil then
      local deal = Game.GetCiv5AiProposedDeal(fromID, toID)
      table.insert(pending, {
        request_id = Civ5Ai_Diplo._RequestId(toID, fromID),
        from_player_id = Civ5Ai_Util.PlayerId(fromID),
        kind = Civ5Ai_Diplo._PendingRequestKind(deal),
        our_items = Civ5Ai_Diplo._DealItemsForPlayer(deal, playerID),
        their_items = Civ5Ai_Diplo._DealItemsForPlayer(deal, fromID),
        legal_response_ids = { "DIPLO_ACCEPT", "DIPLO_REJECT" },
      })
    end
  end
  return pending
end

function Civ5Ai_Diplo.BuildActiveDeals(playerID)
  local deals = Civ5Ai_Util.JsonArrayList()
  if not Civ5Ai_Diplo._DllReady() or Game.GetCiv5AiNumCurrentDeals == nil then
    return deals
  end
  local count = Game.GetCiv5AiNumCurrentDeals(playerID) or 0
  for index = 0, count - 1 do
    local deal = Game.GetCiv5AiCurrentDeal(playerID, index)
    if deal ~= nil then
      local fromID = deal:GetFromPlayer()
      local toID = deal:GetToPlayer()
      local otherID = fromID
      if fromID == playerID then
        otherID = toID
      end
      local dealGetId = 0
      if deal.GetID ~= nil then
        dealGetId = deal:GetID() or 0
      end
      local startTurn = 0
      if deal.GetStartTurn ~= nil then
        startTurn = deal:GetStartTurn() or 0
      end
      local gameTurn = 0
      if Game ~= nil and Game.GetGameTurn ~= nil then
        gameTurn = Game.GetGameTurn() or 0
      end
      local turnsActive = gameTurn - startTurn
      if turnsActive < 0 then
        turnsActive = 0
      end
      table.insert(deals, {
        deal_id = "DEAL_" .. tostring(playerID) .. "_" .. tostring(otherID) .. "_" .. tostring(dealGetId),
        other_player_id = Civ5Ai_Util.PlayerId(otherID),
        our_items = Civ5Ai_Diplo._DealItemsForPlayer(deal, playerID),
        their_items = Civ5Ai_Diplo._DealItemsForPlayer(deal, otherID),
        turns_active = turnsActive,
        cancelable = true,
      })
    end
  end
  return deals
end

function Civ5Ai_Diplo.BuildLegalCommands(playerID, diplomacy)
  local commands = {}
  local lastMajor = 21
  if GameDefines ~= nil and GameDefines.MAX_MAJOR_CIVS ~= nil then
    lastMajor = GameDefines.MAX_MAJOR_CIVS - 1
  end
  local us = Players[playerID]
  local usTeam = us ~= nil and Teams[us:GetTeam()] or nil
  for otherID = 0, lastMajor do
    if otherID ~= playerID and Civ5Ai_Diplo._MetMajor(playerID, otherID) then
      local other = Players[otherID]
      if usTeam ~= nil and other ~= nil and usTeam.CanDeclareWar ~= nil then
        local theirTeam = other:GetTeam()
        if usTeam:CanDeclareWar(theirTeam) then
          local targetId = Civ5Ai_Util.PlayerId(otherID)
          table.insert(commands, {
            kind = "declare_war",
            command_id = "CMD_declare_war_" .. targetId,
            description = "Declare war on " .. targetId,
            fixed_arguments = { target_player_id = targetId },
            affected_ids = { targetId },
            parameter_domains = {},
            runtime_status = "tested",
          })
        end
      end
    end
  end
  if not Civ5Ai_Diplo._DllReady() then
    return commands
  end
  for _, proposal in ipairs(diplomacy.available_proposals or {}) do
    local kindToken = Civ5Ai_Diplo._ParseProposalId(proposal.proposal_id)
    table.insert(commands, {
      kind = "propose_deal",
      command_id = "CMD_propose_" .. proposal.proposal_id,
      description = "Propose " .. tostring(kindToken or "deal") .. " to " .. proposal.target_player_id,
      fixed_arguments = {
        proposal_id = proposal.proposal_id,
        target_player_id = proposal.target_player_id,
      },
      affected_ids = { proposal.target_player_id },
      parameter_domains = {},
      runtime_status = "tested",
    })
  end
  for _, request in ipairs(diplomacy.pending_requests or {}) do
    local requestId = request.request_id
    table.insert(commands, {
      kind = "respond_to_deal",
      command_id = "CMD_accept_" .. requestId,
      description = "Accept trade from " .. request.from_player_id,
      fixed_arguments = { request_id = requestId, response_id = "DIPLO_ACCEPT" },
      affected_ids = { request.from_player_id },
      parameter_domains = {},
      runtime_status = "tested",
    })
    table.insert(commands, {
      kind = "respond_to_deal",
      command_id = "CMD_reject_" .. requestId,
      description = "Reject trade from " .. request.from_player_id,
      fixed_arguments = { request_id = requestId, response_id = "DIPLO_REJECT" },
      affected_ids = { request.from_player_id },
      parameter_domains = {},
      runtime_status = "tested",
    })
  end
  for _, deal in ipairs(diplomacy.active_deals or {}) do
    if deal.cancelable then
      table.insert(commands, {
        kind = "cancel_deal",
        command_id = "CMD_cancel_" .. deal.deal_id,
        description = "Cancel deal with " .. deal.other_player_id,
        fixed_arguments = { deal_id = deal.deal_id },
        affected_ids = { deal.other_player_id },
        parameter_domains = {},
        runtime_status = "tested",
      })
    end
  end
  return commands
end

function Civ5Ai_Diplo.ProposeDeal(playerID, args)
  local proposalId = args.proposal_id
  local kindToken, targetID = Civ5Ai_Diplo._ParseProposalId(proposalId)
  if kindToken == nil and args.target_player_id ~= nil then
    targetID = tonumber(string.match(tostring(args.target_player_id), "PLAYER_(%d+)"))
    kindToken = args.catalog_kind
  end
  if targetID == nil or kindToken == nil then
    return false, "invalid_proposal_id"
  end
  local catalog = Civ5Ai_Diplo._CatalogEntryForKind(kindToken)
  if catalog == nil then
    return false, "unknown_catalog_kind"
  end
  if not Civ5Ai_Diplo._CanOfferCatalog(playerID, targetID, catalog) then
    return false, "proposal_not_legal"
  end
  if Game.Civ5AiQueueCatalogDeal(playerID, targetID, catalog.kind) then
    Civ5Ai_Chat.PostPrivateTradeLine(playerID, targetID, "Trade proposal: " .. catalog.label)
    return true, ""
  end
  return false, "queue_failed"
end

function Civ5Ai_Diplo.ResolvePendingDeals(playerID, responseId)
  local pending = Civ5Ai_Diplo.BuildPendingRequests(playerID)
  local resolved = 0
  for _, request in ipairs(pending) do
    local ok = Civ5Ai_Diplo.RespondToDeal(playerID, {
      request_id = request.request_id,
      response_id = responseId,
    })
    if ok then
      resolved = resolved + 1
    end
  end
  Civ5Ai_Util.Log(
    "diplo|resolve_pending|player="
      .. tostring(playerID)
      .. "|response="
      .. tostring(responseId)
      .. "|count="
      .. tostring(resolved)
  )
  return resolved
end

Civ5Ai_Diplo._TRADE_UI_PATHS = {
  "/InGame/DiploCorner/SimpleDiplo",
  "/InGame/WorldView/SimpleDiploTrade",
  "/LeaderHeadRoot/DiploTrade",
  "/LeaderHeadRoot/DiscussionDialog",
}

function Civ5Ai_Diplo._ShouldDeferTradeUi(playerID)
  return Civ5Ai_Seats ~= nil and Civ5Ai_Seats.UsesFullLlmControl(playerID)
end

function Civ5Ai_Diplo._ScratchDealHasItems(deal)
  if deal == nil or deal.ResetIterator == nil then
    return false
  end
  deal:ResetIterator()
  local itemType = deal:GetNextItem()
  return itemType ~= nil
end

function Civ5Ai_Diplo._QueueVisibleScratchDeal(recipientID)
  if not Civ5Ai_Diplo._DllReady() or Game.Civ5AiQueueScratchDeal == nil then
    return false
  end
  if UI == nil or UI.GetScratchDeal == nil then
    return false
  end
  local deal = UI.GetScratchDeal()
  if not Civ5Ai_Diplo._ScratchDealHasItems(deal) then
    return false
  end
  local fromID = deal.GetFromPlayer ~= nil and deal:GetFromPlayer() or nil
  local toID = deal.GetToPlayer ~= nil and deal:GetToPlayer() or nil
  if toID ~= recipientID or fromID == nil or fromID == recipientID then
    return false
  end
  return Civ5Ai_Diplo.QueueScratchProposal(fromID, toID)
end

function Civ5Ai_Diplo._DeferActiveDiploUi()
  local host = ExposedMembers ~= nil and ExposedMembers.Civ5Ai or nil
  if host ~= nil and host.DeferDiploTradeUi ~= nil and host.DeferDiploTradeUi() then
    return true
  end
  if host ~= nil and host.DeferDiploDiscussionUi ~= nil and host.DeferDiploDiscussionUi() then
    return true
  end
  return false
end

function Civ5Ai_Diplo._TradeUiShowing()
  if Civ5Ai_Apply == nil then
    return false
  end
  if Civ5Ai_Apply._LeaderHeadShowing ~= nil and Civ5Ai_Apply._LeaderHeadShowing() then
    return true
  end
  if Civ5Ai_Apply._ControlVisible == nil then
    return false
  end
  for _, path in ipairs(Civ5Ai_Diplo._TRADE_UI_PATHS) do
    if Civ5Ai_Apply._ControlVisible(path) then
      return true
    end
  end
  return false
end

function Civ5Ai_Diplo._DismissTradeUiWithoutResponse(playerID, reason)
  if not Civ5Ai_Diplo._TradeUiShowing() then
    return false
  end
  -- TradeLogic.OnBack closes leader + DiploTrade together. Dismissing leader
  -- alone orphans the trade panel (GetLeaderHeadRootUp false while trade shows).
  if Civ5Ai_Diplo._DeferActiveDiploUi() then
    Civ5Ai_Util.Log("diplo|dismiss_diplo_ui|" .. tostring(reason or "llm_human"))
    return true
  end
  return false
end

function Civ5Ai_Diplo._PumpTradeUiDismiss(playerID)
  if not Civ5Ai_Diplo._ShouldDeferTradeUi(playerID) then
    return
  end
  if Civ5Ai_Diplo._tradeDismissPumpActive then
    return
  end
  Civ5Ai_Diplo._tradeDismissPumpActive = true
  local attempts = 0
  Civ5Ai_Util.ScheduleTick(function()
    attempts = attempts + 1
    if Game == nil or Game.GetActivePlayer == nil or Game.GetActivePlayer() ~= playerID then
      Civ5Ai_Diplo._tradeDismissPumpActive = false
      return false
    end
    if not Civ5Ai_Diplo._TradeUiShowing() then
      Civ5Ai_Diplo._tradeDismissPumpActive = false
      return false
    end
    Civ5Ai_Diplo.HandleLeaderTradeBlocker(playerID)
    if Civ5Ai_Autotest ~= nil and Civ5Ai_Autotest._ReleaseUiFocus ~= nil then
      Civ5Ai_Autotest._ReleaseUiFocus()
    end
    if attempts >= 180 then
      Civ5Ai_Util.Log("diplo|dismiss_trade_ui|give_up|attempts=" .. tostring(attempts))
      Civ5Ai_Diplo._tradeDismissPumpActive = false
      return false
    end
    return true
  end)
end

function Civ5Ai_Diplo._PulseForPendingDeal(playerID, requestId)
  if not Civ5Ai_Config.IsSidecarLive() or Civ5Ai_Bridge == nil then
    return false
  end
  if Civ5Ai_Diplo._leaderPulseKey == requestId then
    return true
  end
  Civ5Ai_Diplo._leaderPulseKey = requestId
  Civ5Ai_Bridge.RequestTurnPulse(playerID)
  if Civ5Ai_Bridge._KickPulseQueue ~= nil then
    Civ5Ai_Bridge._KickPulseQueue()
  end
  return true
end

function Civ5Ai_Diplo._OnTradeUiOpened(playerID)
  if not Civ5Ai_Diplo._ShouldDeferTradeUi(playerID) then
    return
  end
  Civ5Ai_Diplo._PumpTradeUiDismiss(playerID)
end

-- LLM-human seats close trade UI immediately (no accept/reject) so the map stays
-- visible. Pending deals stay on the async queue for the sidecar wire response.
function Civ5Ai_Diplo.HandleLeaderTradeBlocker(playerID)
  if Civ5Ai_Diplo._ShouldDeferTradeUi(playerID) then
    local dismissed = Civ5Ai_Diplo._DismissTradeUiWithoutResponse(playerID, "llm_human")
    local pending = Civ5Ai_Diplo.BuildPendingRequests(playerID)
    if #pending > 0 then
      local requestId = pending[1].request_id
      Civ5Ai_Util.Log(
        "diplo|leader_trade|player="
          .. tostring(playerID)
          .. "|pending="
          .. tostring(#pending)
          .. "|deferred=1"
      )
      if Civ5Ai_Config.IsSidecarLive() and Civ5Ai_Bridge ~= nil then
        Civ5Ai_Diplo._PulseForPendingDeal(playerID, requestId)
      else
        Civ5Ai_Diplo.ResolvePendingDeals(playerID, "DIPLO_REJECT")
        Civ5Ai_Diplo._leaderPulseKey = nil
        return dismissed and "dismissed" or "rejected"
      end
    else
      Civ5Ai_Diplo._leaderPulseKey = nil
    end
    return dismissed and "dismissed" or nil
  end

  local pending = Civ5Ai_Diplo.BuildPendingRequests(playerID)
  if #pending == 0 then
    Civ5Ai_Diplo._leaderPulseKey = nil
    return nil
  end
  local requestId = pending[1].request_id
  Civ5Ai_Util.Log(
    "diplo|leader_trade|player="
      .. tostring(playerID)
      .. "|pending="
      .. tostring(#pending)
  )
  if Civ5Ai_Config.IsSidecarLive() and Civ5Ai_Bridge ~= nil then
    Civ5Ai_Diplo._PulseForPendingDeal(playerID, requestId)
    return nil
  end
  Civ5Ai_Diplo.ResolvePendingDeals(playerID, "DIPLO_REJECT")
  Civ5Ai_Diplo._leaderPulseKey = nil
  return "rejected"
end

function Civ5Ai_Diplo.RespondToDeal(playerID, args)
  local requestId = args.request_id
  local responseId = args.response_id
  local recipientID, senderID = Civ5Ai_Diplo._ParseRequestId(requestId)
  if recipientID ~= playerID or senderID == nil then
    return false, "invalid_request_id"
  end
  if responseId == "DIPLO_REJECT" then
    if Game.Civ5AiFinalizeDeal(senderID, recipientID, false) then
      Civ5Ai_Diplo._CompleteDiscussionFollowup(senderID, recipientID, false)
      return true, ""
    end
    return false, "reject_failed"
  end
  if responseId == "DIPLO_ACCEPT" then
    if Game.Civ5AiFinalizeDeal(senderID, recipientID, true) then
      Civ5Ai_Diplo._CompleteDiscussionFollowup(senderID, recipientID, true)
      return true, ""
    end
    return false, "accept_failed"
  end
  return false, "invalid_response"
end

function Civ5Ai_Diplo.CancelDeal(playerID, args)
  local dealId = args.deal_id
  local owner, other, dealGetId = string.match(dealId or "", "^DEAL_(%d+)_(%d+)_(%d+)$")
  if owner == nil then
    return false, "invalid_deal_id"
  end
  owner = tonumber(owner)
  dealGetId = tonumber(dealGetId)
  if owner ~= playerID then
    return false, "deal_not_owned"
  end
  if Game.Civ5AiCancelCurrentDealById == nil then
    return false, "cancel_by_id_missing"
  end
  if Game.Civ5AiCancelCurrentDealById(playerID, dealGetId) then
    return true, ""
  end
  return false, "cancel_failed"
end

function Civ5Ai_Diplo._ParsePlayerId(value)
  if value == nil then
    return nil
  end
  if type(value) == "number" then
    return value
  end
  return tonumber(string.match(tostring(value), "PLAYER_(%d+)"))
end

function Civ5Ai_Diplo.DeclareWar(playerID, args)
  local targetID = Civ5Ai_Diplo._ParsePlayerId(args.target_player_id)
  if targetID == nil then
    return false, "invalid_target"
  end
  local us = Players[playerID]
  local other = Players[targetID]
  if us == nil or other == nil then
    return false, "player_not_found"
  end
  local usTeam = Teams[us:GetTeam()]
  local theirTeamID = other:GetTeam()
  if usTeam == nil or theirTeamID == nil or us:GetTeam() == theirTeamID then
    return false, "cannot_declare_war_on_self"
  end
  if usTeam.CanDeclareWar == nil or not usTeam:CanDeclareWar(theirTeamID) then
    return false, "cannot_declare_war"
  end
  -- Network.SendChangeWar always uses the local active human. In co-active mode
  -- that makes seat 0 declare war on its own team when another seat applies war.
  if usTeam.DeclareWar ~= nil then
    usTeam:DeclareWar(theirTeamID)
  elseif Game ~= nil
    and Game.GetActivePlayer ~= nil
    and Game.GetActivePlayer() == playerID
    and Network ~= nil
    and Network.SendChangeWar ~= nil then
    Network.SendChangeWar(theirTeamID, true)
  else
    return false, "declare_war_requires_team_api"
  end
  local theirTeam = Teams[theirTeamID]
  local isMinor = theirTeam ~= nil and theirTeam.IsMinorCiv ~= nil and theirTeam:IsMinorCiv()
  local isHuman = theirTeam ~= nil and theirTeam.IsHuman ~= nil and theirTeam:IsHuman()
  if not isMinor and not isHuman
    and Game ~= nil
    and Game.DoFromUIDiploEvent ~= nil
    and FromUIDiploEventTypes ~= nil then
    Game.DoFromUIDiploEvent(
      FromUIDiploEventTypes.FROM_UI_DIPLO_EVENT_HUMAN_DECLARES_WAR,
      targetID,
      0,
      0
    )
  end
  Civ5Ai_Util.Log(
    "apply|declare_war|player=" .. tostring(playerID) .. "|target=" .. tostring(targetID)
  )
  return true, ""
end

function Civ5Ai_Diplo.QueueScratchProposal(fromID, toID)
  if fromID == nil or toID == nil or not Civ5Ai_Diplo._DllReady() then
    return false
  end
  if Civ5Ai_Config.IsManagedSeat(toID) and Game.Civ5AiQueueScratchDeal(fromID, toID) then
    Civ5Ai_Chat.PostPrivateTradeLine(fromID, toID, "We sent a trade proposal for your consideration.")
    Civ5Ai_Util.Log("diplo|queue_scratch|from=" .. tostring(fromID) .. "|to=" .. tostring(toID))
    return true
  end
  return false
end

function Civ5Ai_Diplo.Initialize()
  Civ5Ai_Diplo._discussionFollowups = Civ5Ai_Diplo._discussionFollowups or {}
  if Civ5Ai_Diplo._tradeUiHooks then
    Civ5Ai_Util.Log("diplo|ready")
    return
  end
  Civ5Ai_Diplo._tradeUiHooks = true
  if Events ~= nil then
    if Events.AILeaderMessage ~= nil then
      Events.AILeaderMessage.Add(function()
        local active = Game.GetActivePlayer()
        Civ5Ai_Diplo._OnTradeUiOpened(active)
      end)
    end
    if Events.OpenPlayerDealScreenEvent ~= nil then
      Events.OpenPlayerDealScreenEvent.Add(function(otherPlayer)
        local active = Game.GetActivePlayer()
        if otherPlayer == active then
          return
        end
        Civ5Ai_Diplo._OnTradeUiOpened(active)
      end)
    end
  end
  Civ5Ai_Util.Log("diplo|ready")
end
