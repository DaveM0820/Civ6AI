-- Send a command string with SendCiv5AiCommands so every machine applies the same orders.
Civ5Ai_Net = Civ5Ai_Net or {}

local PREFIX = "CIV5AI:"

function Civ5Ai_Net._IsHost()
  if Game ~= nil and Game.IsHost ~= nil then
    return Game.IsHost() == true
  end
  return true
end

function Civ5Ai_Net._UnitMoves(unit)
  if unit == nil then
    return -1
  end
  if unit.MovesLeft ~= nil then
    return unit:MovesLeft() or -1
  end
  if unit.GetMoves ~= nil then
    return unit:GetMoves() or -1
  end
  return -1
end

function Civ5Ai_Net._PickUnit(playerID)
  local player = Players[playerID]
  if player == nil then
    return nil
  end
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() then
      local ready = false
      if unit.IsReadyToMove ~= nil then
        ready = unit:IsReadyToMove() == true
      else
        ready = Civ5Ai_Net._UnitMoves(unit) > 0
      end
      if ready then
        return unit
      end
    end
  end
  for unit in player:Units() do
    if unit ~= nil and not unit:IsDead() then
      return unit
    end
  end
  return nil
end

function Civ5Ai_Net._VehicleUnit(playerID)
  return Civ5Ai_Net._PickUnit(playerID)
end

function Civ5Ai_Net._EncodeCommand(command)
  return Civ5Ai_Commands.EncodeNet(command)
end

function Civ5Ai_Net._EncodeChat(message)
  if message == nil or message.text == nil or message.text == "" then
    return nil
  end
  local encoded = Civ5Ai_Util.Base64Encode(message.text)
  local target = tostring(message.target or "all")
  if target == "player" then
    local dest = tostring(message.target_player_id or "")
    dest = string.gsub(dest, "^PLAYER_", "")
    return "chat:player:" .. dest .. ":" .. encoded
  end
  if target == "team" then
    return "chat:team:" .. encoded
  end
  return "chat:all:" .. encoded
end

function Civ5Ai_Net.EncodeDecision(playerID, decision)
  local parts = { "apply", tostring(playerID) }
  if decision ~= nil and decision.commands ~= nil then
    for _, command in ipairs(decision.commands) do
      local token = Civ5Ai_Net._EncodeCommand(command)
      if token ~= nil then
        table.insert(parts, token)
      end
    end
  end
  if decision ~= nil and decision.chat_messages ~= nil then
    for _, message in ipairs(decision.chat_messages) do
      local token = Civ5Ai_Net._EncodeChat(message)
      if token ~= nil then
        table.insert(parts, token)
      end
    end
  end
  return table.concat(parts, "|")
end

function Civ5Ai_Net._DecodeToken(token)
  local kind, rest = string.match(token, "^([^:]+):(.+)$")
  if kind == nil then
    return nil
  end
  if kind == "chat" then
    local target, payload = string.match(rest, "^([^:]+):(.+)$")
    if target == nil then
      return nil
    end
    if target == "player" then
      local dest, b64 = string.match(payload, "^([^:]+):(.+)$")
      if dest == nil then
        return nil
      end
      return {
        _chat = true,
        target = "player",
        target_player_id = dest,
        text = Civ5Ai_Util.Base64Decode(b64) or "",
      }
    end
    return {
      _chat = true,
      target = target,
      text = Civ5Ai_Util.Base64Decode(payload) or "",
    }
  end
  return Civ5Ai_Commands.DecodeNet(token)
end

function Civ5Ai_Net._ApplyEncoded(playerID, tokens)
  if Civ5Ai_Bridge ~= nil and Civ5Ai_Bridge._WasAppliedThisPulse ~= nil then
    if Civ5Ai_Bridge._WasAppliedThisPulse(playerID) then
      Civ5Ai_Util.Log("net|recv|skip_duplicate|player=" .. tostring(playerID))
      return
    end
  end
  local commands = {}
  local chats = {}
  for i = 1, #tokens do
    local item = Civ5Ai_Net._DecodeToken(tokens[i])
    if item ~= nil then
      if item._chat then
        table.insert(chats, item)
      else
        table.insert(commands, item)
      end
    end
  end
  if #commands == 0 and #chats == 0 then
    Civ5Ai_Util.Log("net|recv|empty_apply|player=" .. tostring(playerID))
    return
  end
  Civ5Ai_Util.Log(
    "net|recv|apply|player="
      .. tostring(playerID)
      .. "|commands="
      .. tostring(#commands)
      .. "|chat="
      .. tostring(#chats)
  )
  if #commands > 0 then
    Civ5Ai_Apply.ApplyDecision(playerID, { commands = commands })
  end
  if #chats > 0 and Civ5Ai_Bridge ~= nil and Civ5Ai_Bridge._ApplyChat ~= nil then
    Civ5Ai_Bridge._ApplyChat(playerID, chats)
  end
  if Civ5Ai_Bridge ~= nil and Civ5Ai_Bridge._MarkApplied ~= nil then
    Civ5Ai_Bridge._MarkApplied(playerID)
  end
  Civ5Ai_Util.Log(
    "net|apply|ok|player=" .. tostring(playerID) .. "|commands=" .. tostring(#commands)
  )
end

function Civ5Ai_Net.BroadcastDecision(playerID, decision)
  if Game.SendCiv5AiCommands == nil then
    Civ5Ai_Util.Log("net|broadcast|unavailable")
    return false
  end
  local payload = Civ5Ai_Net.EncodeDecision(playerID, decision)
  local vehicle = Civ5Ai_Net._VehicleUnit(playerID)
  if vehicle == nil then
    Civ5Ai_Util.Log("net|broadcast|no_unit|player=" .. tostring(playerID))
    return false
  end
  Civ5Ai_Util.Log(
    "net|broadcast|player="
      .. tostring(playerID)
      .. "|unit="
      .. tostring(vehicle:GetID())
      .. "|payload="
      .. payload
  )
  Game.SendCiv5AiCommands(payload, vehicle:GetID())
  return true
end

function Civ5Ai_Net.BroadcastJson(playerID, jsonText)
  if jsonText == nil or jsonText == "" then
    return false
  end
  local decision = jsonText
  if type(jsonText) == "string" then
    if Civ5Ai_Bridge == nil or Civ5Ai_Bridge._ParseDecision == nil then
      Civ5Ai_Util.Log("net|broadcast|no_parser")
      return false
    end
    decision = Civ5Ai_Bridge._ParseDecision(jsonText)
  end
  return Civ5Ai_Net.BroadcastDecision(playerID, decision)
end

function Civ5Ai_Net.OnCommands(playerID, payload)
  local text = tostring(payload or "")
  if string.sub(text, 1, #PREFIX) == PREFIX then
    text = string.sub(text, #PREFIX + 1)
  end
  local parts = {}
  for part in string.gmatch(text, "[^|]+") do
    table.insert(parts, part)
  end
  if #parts == 0 then
    Civ5Ai_Util.Log("net|recv|bad_payload|" .. tostring(payload))
    return
  end
  if parts[1] == "apply" then
    local ownerID = tonumber(parts[2])
    if ownerID == nil then
      Civ5Ai_Util.Log("net|recv|bad_payload|" .. tostring(payload))
      return
    end
    local tokens = {}
    for i = 3, #parts do
      table.insert(tokens, parts[i])
    end
    Civ5Ai_Net._ApplyEncoded(ownerID, tokens)
    return
  end
  Civ5Ai_Util.Log("net|recv|bad_payload|" .. tostring(payload))
end

function Civ5Ai_Net.Initialize()
  if Civ5Ai_Net._hooks then
    return
  end
  if GameEvents ~= nil and GameEvents.Civ5AiCommands ~= nil then
    GameEvents.Civ5AiCommands.Add(Civ5Ai_Net.OnCommands)
    Civ5Ai_Util.Log("net|recv_event|ok")
  else
    local ok, err = pcall(function()
      GameEvents.Civ5AiCommands.Add(Civ5Ai_Net.OnCommands)
    end)
    if ok then
      Civ5Ai_Util.Log("net|recv_event|ok")
    else
      Civ5Ai_Util.Log("net|recv_event|unavailable|" .. tostring(err))
    end
  end
  local preOk, preErr = pcall(function()
    GameEvents.PlayerPreAIUnitUpdate.Add(Civ5Ai_Net.OnPlayerPreAIUnitUpdate)
  end)
  if preOk then
    Civ5Ai_Util.Log("net|pre_ai_unit_update|ok")
  else
    Civ5Ai_Util.Log("net|pre_ai_unit_update|unavailable|" .. tostring(preErr))
  end
  Civ5Ai_Net._hooks = true
  Civ5Ai_Util.Log("net|init|ok")
end

function Civ5Ai_Net.OnPlayerPreAIUnitUpdate(playerID)
  -- Hold native AI during the cascade; FinishSeat releases so leftover MP
  -- stays for Community Patch after LLM apply.
  if Civ5Ai_Bridge == nil or Civ5Ai_Bridge.ShouldSkipNativeUnitAi == nil then
    return false
  end
  local skip = Civ5Ai_Bridge.ShouldSkipNativeUnitAi(playerID)
  Civ5Ai_Util.Log(
    "net|pre_ai_unit_update|player=" .. tostring(playerID) .. "|skip=" .. tostring(skip)
  )
  return skip
end
