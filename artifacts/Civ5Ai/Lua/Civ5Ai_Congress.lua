-- World Congress snapshot, legal commands, and apply handlers.
Civ5Ai_Congress = Civ5Ai_Congress or {}

local kChoiceNone = -1
local kChoiceNo = 0
local kChoiceYes = 1

function Civ5Ai_Congress._League()
  if Game == nil or Game.GetActiveLeague == nil then
    return nil
  end
  return Game.GetActiveLeague()
end

function Civ5Ai_Congress._LeagueId(league)
  if league == nil then
    return -1
  end
  if league.GetID ~= nil then
    return league:GetID()
  end
  return 0
end

function Civ5Ai_Congress._DecisionChoices(league, decisionTypeName, playerID)
  local choices = Civ5Ai_Util.JsonArrayList()
  if league == nil or decisionTypeName == nil or GameInfo.ResolutionDecisions == nil then
    return choices
  end
  local decisionRow = GameInfo.ResolutionDecisions[decisionTypeName]
  if decisionRow == nil then
    return choices
  end
  local decisionId = decisionRow.ID
  if league.GetChoicesForDecision == nil then
    return choices
  end
  for _, choiceId in ipairs(league:GetChoicesForDecision(decisionId, playerID)) do
    local label = choiceId
    if league.GetTextForChoice ~= nil then
      label = league:GetTextForChoice(decisionId, choiceId) or choiceId
    end
    table.insert(choices, {
      choice_id = choiceId,
      label = tostring(label),
    })
  end
  return choices
end

function Civ5Ai_Congress._VoterChoices(league, resolutionType, playerID)
  local row = GameInfo.Resolutions[resolutionType]
  if row == nil or row.VoterDecision == nil then
    return Civ5Ai_Util.JsonArrayList()
  end
  return Civ5Ai_Congress._DecisionChoices(league, row.VoterDecision, playerID)
end

function Civ5Ai_Congress._ProposerChoices(league, resolutionType, playerID)
  local row = GameInfo.Resolutions[resolutionType]
  if row == nil or row.ProposerDecision == nil then
    return Civ5Ai_Util.JsonArrayList()
  end
  local choices = Civ5Ai_Congress._DecisionChoices(league, row.ProposerDecision, playerID)
  if #choices == 0 then
    table.insert(choices, {
      choice_id = kChoiceNone,
      label = "default",
      legal = league.CanProposeEnact ~= nil
        and league:CanProposeEnact(resolutionType, playerID, kChoiceNone) == true,
    })
  else
    for _, choice in ipairs(choices) do
      choice.legal = league.CanProposeEnact ~= nil
        and league:CanProposeEnact(resolutionType, playerID, choice.choice_id) == true
    end
  end
  return choices
end

function Civ5Ai_Congress.BuildBlock(playerID)
  local block = { available = false }
  local league = Civ5Ai_Congress._League()
  if league == nil then
    return block
  end
  block.available = true
  block.league_id = Civ5Ai_Congress._LeagueId(league)
  if league.GetName ~= nil then
    block.name = league:GetName()
  end
  block.in_session = league.IsInSession ~= nil and league:IsInSession() == true
  if league.GetRemainingVotesForMember ~= nil then
    block.votes_remaining = league:GetRemainingVotesForMember(playerID) or 0
  else
    block.votes_remaining = 0
  end
  if league.CanPropose ~= nil then
    block.can_propose = league:CanPropose(playerID) == true
  else
    block.can_propose = false
  end
  if league.GetHostMember ~= nil then
    block.host_player_id = Civ5Ai_Util.PlayerId(league:GetHostMember())
  end
  if Game.GetVotesNeededForDiploVictory ~= nil then
    block.diplo_victory_votes_needed = Game.GetVotesNeededForDiploVictory()
  end

  block.propose_options = Civ5Ai_Util.JsonArrayList()
  block.vote_ballots = Civ5Ai_Util.JsonArrayList()

  if block.can_propose and league.GetInactiveResolutions ~= nil then
    for _, row in ipairs(league:GetInactiveResolutions()) do
      if row ~= nil and #block.propose_options < 24 then
        local resolutionType = row.Type
        if league.CanProposeEnactAnyChoice ~= nil
            and league:CanProposeEnactAnyChoice(resolutionType, playerID) then
          for _, choice in ipairs(Civ5Ai_Congress._ProposerChoices(league, resolutionType, playerID)) do
            if choice.legal ~= false and #block.propose_options < 24 then
              table.insert(block.propose_options, {
                action = "enact",
                resolution_type = resolutionType,
                choice_id = choice.choice_id,
                label = choice.label,
              })
            end
          end
        end
      end
    end
  end

  if block.can_propose and league.GetActiveResolutions ~= nil and league.CanProposeRepeal ~= nil then
    for _, row in ipairs(league:GetActiveResolutions()) do
      if row ~= nil and #block.propose_options < 24 then
        local resolutionId = row.ID
        if league:CanProposeRepeal(resolutionId, playerID) then
          local proposerDecision = row.ProposerDecision or kChoiceNone
          table.insert(block.propose_options, {
            action = "repeal",
            resolution_id = resolutionId,
            resolution_type = row.Type,
            choice_id = kChoiceNone,
            label = league:GetResolutionName(row.Type, resolutionId, proposerDecision, false),
          })
        end
      end
    end
  end

  if block.in_session and (block.votes_remaining or 0) > 0 then
    local function addBallot(proposal, direction)
      if proposal == nil or #block.vote_ballots >= 12 then
        return
      end
      local resolutionType = proposal.Type
      local resolutionId = proposal.ID
      local proposerDecision = proposal.ProposerDecision or kChoiceNone
      table.insert(block.vote_ballots, {
        ballot_id = direction .. "_" .. tostring(resolutionId),
        direction = direction,
        resolution_id = resolutionId,
        resolution_type = resolutionType,
        label = league:GetResolutionName(resolutionType, resolutionId, proposerDecision, false),
        choices = Civ5Ai_Congress._VoterChoices(league, resolutionType, playerID),
      })
    end
    if league.GetEnactProposals ~= nil then
      for _, proposal in ipairs(league:GetEnactProposals()) do
        addBallot(proposal, "enact")
      end
    end
    if league.GetRepealProposals ~= nil then
      for _, proposal in ipairs(league:GetRepealProposals()) do
        addBallot(proposal, "repeal")
      end
    end
  end

  return block
end

function Civ5Ai_Congress.BuildLegalCommands(playerID)
  local commands = {}
  local block = Civ5Ai_Congress.BuildBlock(playerID)
  if block.available ~= true then
    return commands
  end

  for index, option in ipairs(block.propose_options or {}) do
    if index > 24 then
      break
    end
    if option.action == "enact" and option.resolution_type ~= nil then
      local cmdId = "CMD_congress_propose_enact_"
        .. tostring(option.resolution_type)
        .. "_"
        .. tostring(option.choice_id or kChoiceNone)
      table.insert(commands, {
        kind = "congress_propose",
        command_id = cmdId,
        description = "Propose enact " .. tostring(option.resolution_type),
        fixed_arguments = {
          action = "enact",
          resolution_type = option.resolution_type,
          choice_id = option.choice_id or kChoiceNone,
        },
        affected_ids = {},
        parameter_domains = {},
        runtime_status = "tested",
      })
    elseif option.action == "repeal" and option.resolution_id ~= nil then
      local cmdId = "CMD_congress_propose_repeal_" .. tostring(option.resolution_id)
      table.insert(commands, {
        kind = "congress_propose",
        command_id = cmdId,
        description = "Propose repeal resolution " .. tostring(option.resolution_id),
        fixed_arguments = {
          action = "repeal",
          resolution_id = option.resolution_id,
        },
        affected_ids = {},
        parameter_domains = {},
        runtime_status = "tested",
      })
    end
  end

  for _, ballot in ipairs(block.vote_ballots or {}) do
    local direction = ballot.direction
    local resolutionId = ballot.resolution_id
    local choices = ballot.choices or {}
    if #choices == 0 then
      for _, choiceId in ipairs({ kChoiceYes, kChoiceNo }) do
        local cmdId = "CMD_congress_vote_"
          .. tostring(direction)
          .. "_"
          .. tostring(resolutionId)
          .. "_1_"
          .. tostring(choiceId)
        table.insert(commands, {
          kind = "congress_vote",
          command_id = cmdId,
          description = "Vote " .. tostring(direction) .. " on resolution " .. tostring(resolutionId),
          fixed_arguments = {
            action = "vote",
            direction = direction,
            resolution_id = resolutionId,
            votes = 1,
            choice_id = choiceId,
          },
          affected_ids = {},
          parameter_domains = {},
          runtime_status = "tested",
        })
      end
    else
      for _, choice in ipairs(choices) do
        local cmdId = "CMD_congress_vote_"
          .. tostring(direction)
          .. "_"
          .. tostring(resolutionId)
          .. "_1_"
          .. tostring(choice.choice_id)
        table.insert(commands, {
          kind = "congress_vote",
          command_id = cmdId,
          description = "Vote " .. tostring(direction) .. " on resolution " .. tostring(resolutionId),
          fixed_arguments = {
            action = "vote",
            direction = direction,
            resolution_id = resolutionId,
            votes = 1,
            choice_id = choice.choice_id,
          },
          affected_ids = {},
          parameter_domains = {},
          runtime_status = "tested",
        })
      end
    end
  end

  local votesRemaining = block.votes_remaining or 0
  if block.in_session and votesRemaining > 0 then
    table.insert(commands, {
      kind = "congress_vote",
      command_id = "CMD_congress_abstain_" .. tostring(votesRemaining),
      description = "Abstain remaining World Congress votes",
      fixed_arguments = {
        action = "abstain",
        votes = votesRemaining,
      },
      affected_ids = {},
      parameter_domains = {},
      runtime_status = "tested",
    })
  end

  return commands
end

function Civ5Ai_Congress.Propose(playerID, args)
  local league = Civ5Ai_Congress._League()
  if league == nil then
    return false, "no_league"
  end
  if Network == nil then
    return false, "network_missing"
  end
  local leagueId = Civ5Ai_Congress._LeagueId(league)
  local action = args and args.action
  if action == "enact" then
    if Network.SendLeagueProposeEnact == nil then
      return false, "propose_enact_missing"
    end
    local resolutionType = args.resolution_type
    if resolutionType == nil or resolutionType == "" then
      return false, "missing_resolution_type"
    end
    Network.SendLeagueProposeEnact(
      leagueId,
      resolutionType,
      playerID,
      args.choice_id or kChoiceNone
    )
    return true, ""
  end
  if action == "repeal" then
    if Network.SendLeagueProposeRepeal == nil then
      return false, "propose_repeal_missing"
    end
    local resolutionId = tonumber(args.resolution_id)
    if resolutionId == nil then
      return false, "missing_resolution_id"
    end
    Network.SendLeagueProposeRepeal(leagueId, resolutionId, playerID)
    return true, ""
  end
  return false, "invalid_propose_action"
end

function Civ5Ai_Congress.Vote(playerID, args)
  local league = Civ5Ai_Congress._League()
  if league == nil then
    return false, "no_league"
  end
  if Network == nil then
    return false, "network_missing"
  end
  local leagueId = Civ5Ai_Congress._LeagueId(league)
  local action = args and args.action
  local votes = tonumber(args.votes) or 1
  if action == "abstain" then
    if Network.SendLeagueVoteAbstain == nil then
      return false, "vote_abstain_missing"
    end
    Network.SendLeagueVoteAbstain(leagueId, playerID, votes)
    return true, ""
  end
  if action ~= "vote" then
    return false, "invalid_vote_action"
  end
  local resolutionId = tonumber(args.resolution_id)
  if resolutionId == nil then
    return false, "missing_resolution_id"
  end
  local choiceId = args.choice_id
  if choiceId == nil then
    choiceId = kChoiceNone
  end
  local direction = args.direction
  if direction == "enact" then
    if Network.SendLeagueVoteEnact == nil then
      return false, "vote_enact_missing"
    end
    Network.SendLeagueVoteEnact(leagueId, resolutionId, playerID, votes, choiceId)
    return true, ""
  end
  if direction == "repeal" then
    if Network.SendLeagueVoteRepeal == nil then
      return false, "vote_repeal_missing"
    end
    Network.SendLeagueVoteRepeal(leagueId, resolutionId, playerID, votes, choiceId)
    return true, ""
  end
  return false, "invalid_vote_direction"
end

function Civ5Ai_Congress.Initialize()
  Civ5Ai_Util.Log("congress|init")
end
