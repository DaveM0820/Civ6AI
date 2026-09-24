-- Civ5Ai chat: same job as Civ4 sendAiChat + overlay history.
-- Vanilla DiploCorner is the lobby; this module records lines and posts LLM speech.
Civ5Ai_Chat = Civ5Ai_Chat or {}

Civ5Ai_Chat._log = Civ5Ai_Chat._log or {}
Civ5Ai_Chat._maxLog = 120
Civ5Ai_Chat._initialized = false
Civ5Ai_Chat._posting = false
Civ5Ai_Chat._postedKeys = Civ5Ai_Chat._postedKeys or {}

-- Firaxis Events.GameMessageChat is listen-only ("Don't call this"). SP lobby paint
-- and AI speech use a mod LuaEvent that DiploCorner already listens to.
function Civ5Ai_Chat._EnsureChatEvent()
  if LuaEvents == nil then
    return false
  end
  if LuaEvents.Civ5AiChat ~= nil then
    return true
  end
  local handlers = {}
  local event = {}
  event.Add = function(fn)
    table.insert(handlers, fn)
  end
  local function fire(fromPlayer, toPlayer, text, chatType)
    for _, fn in ipairs(handlers) do
      fn(fromPlayer, toPlayer, text, chatType)
    end
  end
  LuaEvents.Civ5AiChat = setmetatable(event, { __call = function(_, ...)
    fire(...)
  end })
  return true
end

function Civ5Ai_Chat._Turn()
  if Game ~= nil and Game.GetGameTurn ~= nil then
    return Game.GetGameTurn()
  end
  return 0
end

function Civ5Ai_Chat._PlayerIndex(value)
  if value == nil then
    return nil
  end
  if type(value) == "number" then
    return value
  end
  local numeric = string.match(tostring(value), "PLAYER_(%d+)")
  if numeric ~= nil then
    return tonumber(numeric)
  end
  return tonumber(value)
end

function Civ5Ai_Chat._ChatType(target)
  local kind = tostring(target or "all")
  if kind == "team" then
    return ChatTargetTypes.CHATTARGET_TEAM, "team"
  end
  if kind == "player" then
    return ChatTargetTypes.CHATTARGET_PLAYER, "player"
  end
  return ChatTargetTypes.CHATTARGET_ALL, "all"
end

function Civ5Ai_Chat._ShouldDisplay(fromPlayer, toPlayer, targetKind)
  local localPlayer = Game.GetActivePlayer()
  if targetKind == "all" or targetKind == "team" then
    return true
  end
  return toPlayer == localPlayer or fromPlayer == localPlayer
end

function Civ5Ai_Chat._Record(fromPlayer, toPlayer, targetKind, text)
  if text == nil or text == "" then
    return
  end
  table.insert(Civ5Ai_Chat._log, {
    turn = Civ5Ai_Chat._Turn(),
    from_player_id = Civ5Ai_Util.PlayerId(fromPlayer),
    to_player_id = toPlayer ~= nil and toPlayer >= 0 and Civ5Ai_Util.PlayerId(toPlayer) or nil,
    target = targetKind,
    text = text,
  })
  while #Civ5Ai_Chat._log > Civ5Ai_Chat._maxLog do
    table.remove(Civ5Ai_Chat._log, 1)
  end
end

function Civ5Ai_Chat._Clip(text, maxLen)
  if text == nil then
    return ""
  end
  local value = tostring(text)
  if maxLen == nil or #value <= maxLen then
    return value
  end
  return string.sub(value, 1, maxLen)
end

function Civ5Ai_Chat.PublicEvents()
  return Civ5Ai_Chat.VisibleEvents(nil)
end

function Civ5Ai_Chat.VisibleEvents(playerID)
  local playerId = playerID ~= nil and Civ5Ai_Util.PlayerId(playerID) or nil
  local events = Civ5Ai_Util.JsonArrayList()
  -- Public feed is broadcast only; private DMs live in PrivateInbox (duplicating here doubled the prompt).
  for _, row in ipairs(Civ5Ai_Chat._log) do
    if row.target == "all" then
      table.insert(events, {
        turn = row.turn,
        kind = "CHAT_PUBLIC",
        summary = Civ5Ai_Chat._Clip(row.text, 800),
        affected_ids = { row.from_player_id },
      })
    end
  end
  return events
end

function Civ5Ai_Chat.PrivateInbox(playerID)
  local playerId = Civ5Ai_Util.PlayerId(playerID)
  local inbox = Civ5Ai_Util.JsonArrayList()
  for _, row in ipairs(Civ5Ai_Chat._log) do
    if row.target == "player" and (row.to_player_id == playerId or row.from_player_id == playerId) then
      table.insert(inbox, {
        message_id = "CHAT_" .. tostring(row.turn) .. "_" .. tostring(row.from_player_id) .. "_" .. tostring(row.to_player_id) .. "_" .. tostring(#inbox),
        turn = row.turn,
        from_player_id = row.from_player_id,
        to_player_id = row.to_player_id,
        text = Civ5Ai_Chat._Clip(row.text, 800),
      })
    end
  end
  return inbox
end

function Civ5Ai_Chat._IsPrivateTarget(toPlayer, eTargetType)
  if eTargetType == ChatTargetTypes.CHATTARGET_PLAYER then
    return true
  end
  return toPlayer ~= nil and tonumber(toPlayer) ~= nil and tonumber(toPlayer) >= 0
end

function Civ5Ai_Chat.OnHumanChat(fromPlayer, toPlayer, text, eTargetType)
  if text == nil or text == "" then
    return
  end
  if string.find(text, "CIV5AI|", 1, true) == 1 then
    return
  end
  if not Civ5Ai_Seats.IsLocalHuman(fromPlayer) then
    return
  end
  Civ5Ai_Chat._OnChatLine(fromPlayer, toPlayer, text, eTargetType)
  if Civ5Ai_Chat._IsPrivateTarget(toPlayer, eTargetType) then
    Civ5Ai_Util.Log(
      "chat|human_private|from="
        .. tostring(fromPlayer)
        .. "|to="
        .. tostring(toPlayer)
        .. "|len="
        .. tostring(string.len(text))
    )
  else
    Civ5Ai_Util.Log(
      "chat|human_public|from=" .. tostring(fromPlayer) .. "|len=" .. tostring(string.len(text))
    )
  end
end

function Civ5Ai_Chat.PostPrivateTradeLine(fromPlayer, toPlayer, text)
  return Civ5Ai_Chat.Post(fromPlayer, toPlayer, text, "player")
end

function Civ5Ai_Chat._PostKey(fromPlayer, dest, kind, text)
  return tostring(Civ5Ai_Chat._Turn())
    .. "|"
    .. tostring(fromPlayer)
    .. "|"
    .. tostring(dest)
    .. "|"
    .. kind
    .. "|"
    .. text
end

function Civ5Ai_Chat._SameTextThisTurn(fromPlayer, text)
  local turn = Civ5Ai_Chat._Turn()
  local fromId = Civ5Ai_Util.PlayerId(fromPlayer)
  for _, row in ipairs(Civ5Ai_Chat._log) do
    if row.turn == turn and row.from_player_id == fromId and row.text == text then
      return true
    end
  end
  return false
end

function Civ5Ai_Chat.Post(fromPlayer, toPlayer, text, targetKind)
  if text == nil or text == "" then
    return false
  end
  if Civ5Ai_Chat._SameTextThisTurn(fromPlayer, text) then
    Civ5Ai_Util.Log("chat|skip_duplicate|player=" .. tostring(fromPlayer))
    return false
  end
  local chatType, kind = Civ5Ai_Chat._ChatType(targetKind)
  local dest = toPlayer
  if dest == nil then
    dest = -1
  end
  local postKey = Civ5Ai_Chat._PostKey(fromPlayer, dest, kind, text)
  if Civ5Ai_Chat._postedKeys[postKey] then
    return false
  end
  Civ5Ai_Chat._postedKeys[postKey] = true
  Civ5Ai_Chat._Record(fromPlayer, dest, kind, text)
  if not Civ5Ai_Chat._ShouldDisplay(fromPlayer, dest, kind) then
    return true
  end
  -- Record now; paint the lobby on the UI pump. PlayerDoTurn / net receive
  -- are game-core stacks, and DiploCorner is HUD.
  Civ5Ai_Util.ScheduleTick(function()
    Civ5Ai_Chat._posting = true
    Civ5Ai_Chat._EnsureChatEvent()
    if LuaEvents ~= nil and LuaEvents.Civ5AiChat ~= nil then
      LuaEvents.Civ5AiChat(fromPlayer, dest, text, chatType)
    end
    Civ5Ai_Chat._posting = false
    Civ5Ai_Util.Log(
      "chat|sent|from="
        .. tostring(fromPlayer)
        .. "|to="
        .. tostring(dest)
        .. "|target="
        .. kind
        .. "|len="
        .. tostring(string.len(text))
    )
    return false
  end)
  return true
end

function Civ5Ai_Chat.ApplyMessages(playerID, messages)
  if messages == nil then
    return 0
  end
  local sent = 0
  for _, message in ipairs(messages) do
    if type(message) == "table" then
      local text = message.text
      if text ~= nil and text ~= "" then
        local target = message.target or "all"
        local dest = Civ5Ai_Chat._PlayerIndex(message.target_player_id)
        if dest == nil then
          dest = -1
        end
        if Civ5Ai_Chat.Post(playerID, dest, text, target) then
          sent = sent + 1
        end
      end
    end
  end
  return sent
end

function Civ5Ai_Chat._OnChatLine(fromPlayer, toPlayer, text, eTargetType)
  if Civ5Ai_Chat._posting then
    return
  end
  if text == nil or text == "" then
    return
  end
  local kind = "all"
  if eTargetType == ChatTargetTypes.CHATTARGET_TEAM then
    kind = "team"
  elseif eTargetType == ChatTargetTypes.CHATTARGET_PLAYER then
    kind = "player"
  end
  Civ5Ai_Chat._Record(fromPlayer, toPlayer, kind, text)
  Civ5Ai_Util.Log(
    "chat|recorded|from="
      .. tostring(fromPlayer)
      .. "|to="
      .. tostring(toPlayer)
      .. "|target="
      .. kind
      .. "|len="
      .. tostring(string.len(text))
  )
end

function Civ5Ai_Chat.Initialize()
  if Civ5Ai_Chat._initialized then
    return
  end
  Civ5Ai_Chat._initialized = true
  Civ5Ai_Chat._EnsureChatEvent()
  if Events ~= nil and Events.GameMessageChat ~= nil then
    Events.GameMessageChat.Add(Civ5Ai_Chat._OnChatLine)
  end
  if LuaEvents ~= nil and LuaEvents.Civ5AiChat ~= nil then
    LuaEvents.Civ5AiChat.Add(Civ5Ai_Chat._OnChatLine)
  end
  Civ5Ai_Util.Log("chat|ready")
end
