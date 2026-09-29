-- Civ6Ai chat: LLM send via Network.SendChat + enable vanilla WorldTracker chat in single-player.
Civ6Ai_Chat = Civ6Ai_Chat or {}

Civ6Ai_Chat._worldTrackerChatEnabled = false
Civ6Ai_Chat._publicEvents = Civ6Ai_Chat._publicEvents or {}
Civ6Ai_Chat._privateInbox = Civ6Ai_Chat._privateInbox or {}
Civ6Ai_Chat._chatSeq = Civ6Ai_Chat._chatSeq or 0
Civ6Ai_Chat._maxHistory = 120

function Civ6Ai_Chat._TrimHistory(list)
  while #list > Civ6Ai_Chat._maxHistory do
    table.remove(list, 1)
  end
end

function Civ6Ai_Chat._ChatLogPath()
  if Civ6Ai_Bridge == nil or Civ6Ai_Bridge._SessionDir == nil then
    return nil
  end
  return Civ6Ai_Util.JoinPath(Civ6Ai_Bridge._SessionDir(), "chat_log.jsonl")
end

function Civ6Ai_Chat._PersistRecord(record)
  local path = Civ6Ai_Chat._ChatLogPath()
  if path == nil then
    return
  end
  Civ6Ai_Util.AppendTextLine(path, Civ6Ai_Util.EncodeJsonValue(record))
end

function Civ6Ai_Chat.GetPublicEvents()
  return Civ6Ai_Chat._publicEvents
end

function Civ6Ai_Chat.GetPrivateInbox(playerID)
  return Civ6Ai_Chat._privateInbox[playerID] or {}
end

function Civ6Ai_Chat._IsHumanSender(fromPlayer)
  if Civ6Ai_Config ~= nil and Civ6Ai_Config.IsHumanSeat ~= nil then
    if Civ6Ai_Config.IsHumanSeat(fromPlayer) then
      return true
    end
  end
  -- Autotest: a managed local seat is played by the model, not a person.
  if Civ6Ai_Config ~= nil and Civ6Ai_Config.IsAutotest() and Civ6Ai_Config.IsManagedSeat(fromPlayer) then
    return false
  end
  if Game ~= nil and Game.GetLocalPlayer ~= nil then
    local localPlayer = Game.GetLocalPlayer()
    if localPlayer ~= nil and localPlayer >= 0 and fromPlayer == localPlayer then
      return true
    end
  end
  return false
end

function Civ6Ai_Chat._IsPrivateTarget(toPlayer, eTargetType)
  if toPlayer ~= nil and tonumber(toPlayer) ~= nil and tonumber(toPlayer) >= 0 then
    if ChatTargetTypes ~= nil and eTargetType ~= nil then
      if eTargetType == ChatTargetTypes.CHATTARGET_PLAYER then
        return true
      end
      if eTargetType ~= ChatTargetTypes.CHATTARGET_ALL then
        return true
      end
    else
      return true
    end
  end
  return false
end

function Civ6Ai_Chat._ManagedRecipients(targetPlayer)
  local recipients = {}
  if targetPlayer ~= nil and tonumber(targetPlayer) ~= nil and tonumber(targetPlayer) >= 0 then
    local seat = tonumber(targetPlayer)
    if Civ6Ai_Config ~= nil and Civ6Ai_Config.IsManagedSeat(seat) then
      table.insert(recipients, seat)
    end
    return recipients
  end
  if PlayerConfigurations == nil then
    return recipients
  end
  for playerID, _ in pairs(PlayerConfigurations) do
    if type(playerID) == "number" and Civ6Ai_Config.IsManagedSeat(playerID) then
      table.insert(recipients, playerID)
    end
  end
  table.sort(recipients)
  return recipients
end

function Civ6Ai_Chat._RecordPublicChat(fromPlayer, text, turn)
  local senderId = Civ6Ai_Util.PlayerId(fromPlayer)
  local event = {
    turn = turn,
    kind = "CHAT_PUBLIC",
    text = text,
    affected_ids = { senderId },
  }
  table.insert(Civ6Ai_Chat._publicEvents, event)
  Civ6Ai_Chat._TrimHistory(Civ6Ai_Chat._publicEvents)
  Civ6Ai_Chat._PersistRecord({
    kind = "public",
    turn = turn,
    from_player_id = senderId,
    text = text,
  })
  pcall(Civ6Ai_Chat.PanelOnPublic, fromPlayer, text, turn)
end

function Civ6Ai_Chat._RecordPrivateChat(fromPlayer, toPlayer, text, turn)
  local inbox = Civ6Ai_Chat._privateInbox[toPlayer] or {}
  -- The snapshot schema requires message_id on every private_inbox record;
  -- without it the seat's snapshot failed validation and lost its model turn.
  Civ6Ai_Chat._privateSeq = (Civ6Ai_Chat._privateSeq or 0) + 1
  local messageId = "MSG_T" .. tostring(turn) .. "_" .. tostring(fromPlayer) .. "_" .. tostring(toPlayer)
    .. "_" .. tostring(Civ6Ai_Chat._privateSeq)
  local message = {
    message_id = messageId,
    turn = turn,
    from_player_id = Civ6Ai_Util.PlayerId(fromPlayer),
    text = text,
  }
  table.insert(inbox, message)
  Civ6Ai_Chat._TrimHistory(inbox)
  Civ6Ai_Chat._privateInbox[toPlayer] = inbox
  Civ6Ai_Chat._PersistRecord({
    kind = "private",
    message_id = messageId,
    turn = turn,
    from_player_id = message.from_player_id,
    to_player_id = Civ6Ai_Util.PlayerId(toPlayer),
    text = text,
  })
  pcall(Civ6Ai_Chat.PanelOnPrivate, fromPlayer, toPlayer, text, turn)
end

function Civ6Ai_Chat._TriggerAiReplies(recipients)
  if recipients == nil or #recipients == 0 then
    return
  end
  if Civ6Ai_Config ~= nil and Civ6Ai_Config.IsSidecarLive ~= nil and not Civ6Ai_Config.IsSidecarLive() then
    Civ6Ai_Util.Log("chat|reply_skipped|sidecar_not_live")
    return
  end
  if Civ6Ai_Bridge == nil or Civ6Ai_Bridge.RunChatPulse == nil then
    return
  end
  for _, playerID in ipairs(recipients) do
    Civ6Ai_Bridge.RunChatPulse(playerID)
  end
end

function Civ6Ai_Chat._OnHumanChat(fromPlayer, toPlayer, text, eTargetType)
  if text == nil or text == "" then
    return
  end
  if string.find(text, "CIV6AI|", 1, true) == 1 then
    return
  end
  -- Model chat goes out through Network.SendChat as the local player, so it comes
  -- back here as if the human typed it. Never treat our own messages as human chat
  -- (that echo re-triggered chat pulses for every seat in a loop).
  if Civ6Ai_Chat._ConsumeSelfSent(text) then
    return
  end
  if not Civ6Ai_Chat._IsHumanSender(fromPlayer) then
    return
  end
  local turn = Game.GetCurrentGameTurn()
  local recipients = {}
  if Civ6Ai_Chat._IsPrivateTarget(toPlayer, eTargetType) then
    local target = tonumber(toPlayer)
    Civ6Ai_Chat._RecordPrivateChat(fromPlayer, target, text, turn)
    recipients = Civ6Ai_Chat._ManagedRecipients(target)
    Civ6Ai_Util.Log(
      "chat|human_private|from=" .. tostring(fromPlayer) .. "|to=" .. tostring(target) .. "|len=" .. tostring(string.len(text))
    )
  else
    Civ6Ai_Chat._RecordPublicChat(fromPlayer, text, turn)
    recipients = Civ6Ai_Chat._ManagedRecipients(nil)
    Civ6Ai_Util.Log(
      "chat|human_public|from=" .. tostring(fromPlayer) .. "|len=" .. tostring(string.len(text))
    )
  end
  Civ6Ai_Chat._TriggerAiReplies(recipients)
end

function Civ6Ai_Chat._OnMultiplayerChat(fromPlayer, toPlayer, text, eTargetType)
  Civ6Ai_Chat._OnHumanChat(fromPlayer, toPlayer, text, eTargetType)
end
Civ6Ai_Chat._publicEvents = Civ6Ai_Chat._publicEvents or {}
Civ6Ai_Chat._privateInbox = Civ6Ai_Chat._privateInbox or {}
Civ6Ai_Chat._chatSeq = Civ6Ai_Chat._chatSeq or 0
Civ6Ai_Chat._maxHistory = 120

function Civ6Ai_Chat._LeaderName(playerID)
  if PlayerConfigurations == nil or PlayerConfigurations[playerID] == nil then
    return nil
  end
  local config = PlayerConfigurations[playerID]
  if config.GetLeaderName ~= nil then
    local name = config:GetLeaderName()
    if name ~= nil and name ~= "" then
      return name
    end
  end
  if config.GetPlayerName ~= nil then
    return config:GetPlayerName()
  end
  return nil
end

function Civ6Ai_Chat._ResolveTargetPlayerId(message)
  local explicit = message.target_player_id
  if explicit ~= nil and explicit ~= "" then
    local numeric = string.match(tostring(explicit), "PLAYER_(%d+)")
    if numeric ~= nil then
      return tonumber(numeric)
    end
    return tonumber(explicit)
  end
  local target = tostring(message.target or "")
  if target == "" or target == "all" or target == "public" then
    return nil
  end
  if PlayerConfigurations == nil then
    return nil
  end
  for playerID, config in pairs(PlayerConfigurations) do
    if type(playerID) == "number" and config ~= nil then
      local leader = nil
      if config.GetLeaderName ~= nil then
        leader = config:GetLeaderName()
      end
      local playerName = nil
      if config.GetPlayerName ~= nil then
        playerName = config:GetPlayerName()
      end
      if leader == target or playerName == target then
        return playerID
      end
    end
  end
  return nil
end

function Civ6Ai_Chat._MarkSelfSent(text)
  Civ6Ai_Chat._selfSent = Civ6Ai_Chat._selfSent or {}
  Civ6Ai_Chat._selfSent[text] = (Civ6Ai_Chat._selfSent[text] or 0) + 1
end

function Civ6Ai_Chat._ConsumeSelfSent(text)
  local pending = Civ6Ai_Chat._selfSent and Civ6Ai_Chat._selfSent[text]
  if pending == nil or pending <= 0 then
    return false
  end
  if pending == 1 then
    Civ6Ai_Chat._selfSent[text] = nil
  else
    Civ6Ai_Chat._selfSent[text] = pending - 1
  end
  return true
end

function Civ6Ai_Chat._SendNetworkChat(text, targetType, targetID)
  if Network == nil or Network.SendChat == nil then
    return false
  end
  if ChatTargetTypes == nil then
    return false
  end
  local chatType = targetType or ChatTargetTypes.CHATTARGET_ALL
  local chatId = targetID or -1
  Civ6Ai_Chat._MarkSelfSent(text)
  Network.SendChat(text, chatType, chatId)
  return true
end

function Civ6Ai_Chat.SendMessage(senderPlayerID, message)
  if message == nil or message.text == nil or message.text == "" then
    return false
  end
  local text = tostring(message.text)
  local target = tostring(message.target or "all")
  if target == "all" or target == "public" then
    if Civ6Ai_Chat._SendNetworkChat(text, ChatTargetTypes.CHATTARGET_ALL, -1) then
      -- Record under the real sender (the network echo would say "local player").
      Civ6Ai_Chat._RecordPublicChat(senderPlayerID, text, Game.GetCurrentGameTurn())
      Civ6Ai_Util.Log("chat|sent|player=" .. tostring(senderPlayerID) .. "|target=all")
      return true
    end
    Civ6Ai_Util.Log("chat|failed|player=" .. tostring(senderPlayerID) .. "|target=all")
    return false
  end
  local targetPlayer = Civ6Ai_Chat._ResolveTargetPlayerId(message)
  if targetPlayer ~= nil then
    if Civ6Ai_Chat._SendNetworkChat(text, ChatTargetTypes.CHATTARGET_PLAYER, targetPlayer) then
      Civ6Ai_Chat._RecordPrivateChat(senderPlayerID, targetPlayer, text, Game.GetCurrentGameTurn())
      Civ6Ai_Util.Log(
        "chat|sent|player=" .. tostring(senderPlayerID) .. "|target_player=" .. tostring(targetPlayer)
      )
      return true
    end
  end
  Civ6Ai_Util.Log("chat|failed|player=" .. tostring(senderPlayerID) .. "|target=" .. target)
  return false
end

function Civ6Ai_Chat.SendMessages(senderPlayerID, messages)
  if messages == nil then
    return 0
  end
  local sent = 0
  for _, message in ipairs(messages) do
    if Civ6Ai_Chat.SendMessage(senderPlayerID, message) then
      sent = sent + 1
    end
  end
  return sent
end

function Civ6Ai_Chat._ShouldEnableWorldTrackerChat()
  return Civ6Ai_Config.EnableSinglePlayerChat()
end

function Civ6Ai_Chat._LookupControl(paths)
  if ContextPtr == nil or paths == nil then
    return nil
  end
  for _, path in ipairs(paths) do
    local control = ContextPtr:LookUpControl(path)
    if control ~= nil then
      return control
    end
  end
  return nil
end

function Civ6Ai_Chat.EnableWorldTrackerChat()
  if Civ6Ai_Chat._worldTrackerChatEnabled then
    return true
  end
  local tracker = Civ6Ai_Chat._LookupControl({
    "/InGame/WorldTracker",
    "../WorldTracker",
  })
  if tracker ~= nil and tracker.SetHide ~= nil and tracker:IsHidden() then
    tracker:SetHide(false)
  end
  local chatPanel = Civ6Ai_Chat._LookupControl({
    "/InGame/WorldTracker/ChatPanel",
    "/InGame/WorldTracker/PanelStack/ChatPanel",
    "../WorldTracker/ChatPanel",
    "../WorldTracker/PanelStack/ChatPanel",
  })
  local chatCheck = Civ6Ai_Chat._LookupControl({
    "/InGame/WorldTracker/ChatCheck",
    "../WorldTracker/ChatCheck",
  })
  if chatPanel == nil or chatCheck == nil then
    if not Civ6Ai_Chat._loggedMissingControls then
      Civ6Ai_Chat._loggedMissingControls = true
      Civ6Ai_Util.Log("chat|worldtracker|missing_controls")
    end
    return false
  end
  if chatCheck.SetHide ~= nil then
    chatCheck:SetHide(false)
  end
  if chatPanel.SetHide ~= nil then
    chatPanel:SetHide(false)
  end
  if chatCheck.SetCheck ~= nil then
    chatCheck:SetCheck(true)
  end
  if chatCheck.ReprocessAnchoring ~= nil then
    chatCheck:ReprocessAnchoring()
  end
  if LuaEvents ~= nil and LuaEvents.WorldTracker_OnChatShown ~= nil then
    LuaEvents.WorldTracker_OnChatShown()
  end
  Civ6Ai_Chat._worldTrackerChatEnabled = true
  Civ6Ai_Util.Log("chat|worldtracker|enabled")
  return true
end

function Civ6Ai_Chat._ScheduleWorldTrackerChatEnable()
  if not Civ6Ai_Chat._ShouldEnableWorldTrackerChat() then
    Civ6Ai_Util.Log("chat|worldtracker|skipped_by_config")
    return
  end
  if GameConfiguration ~= nil and GameConfiguration.IsNetworkMultiplayer ~= nil then
    if GameConfiguration.IsNetworkMultiplayer() then
      Civ6Ai_Util.Log("chat|worldtracker|already_mp")
      return
    end
  end
  local attempts = 0
  Civ6Ai_Util.ScheduleTick(function()
    attempts = attempts + 1
    if Civ6Ai_Chat.EnableWorldTrackerChat() then
      return false
    end
    if attempts >= 60 then
      Civ6Ai_Util.Log("chat|worldtracker|enable_timeout")
      return false
    end
    return true
  end)
end

function Civ6Ai_Chat._OnLoadGameViewStateDone()
  Civ6Ai_Chat._ScheduleWorldTrackerChatEnable()
end

-- ---------------------------------------------------------------------------
-- Chat panel (Civ6Ai_InGame.xml). Shows public AI chat and private messages to
-- the local player or a human seat; the edit box sends the local player's
-- message to the AI seats (@LeaderName text = private).
-- ---------------------------------------------------------------------------
Civ6Ai_Chat.PANEL_MAX_LINES = 80
Civ6Ai_Chat.PANEL_PLACEHOLDER = "AI chat will appear here."
Civ6Ai_Chat._panelLines = Civ6Ai_Chat._panelLines or {}

function Civ6Ai_Chat._PanelControls()
  if Controls == nil or Controls.Civ6AiChatLog == nil then
    return nil
  end
  return Controls
end

function Civ6Ai_Chat._PanelName(playerID)
  local id = tonumber(playerID)
  if id ~= nil and Game ~= nil and Game.GetLocalPlayer ~= nil and Game.GetLocalPlayer() == id
      and Civ6Ai_Chat._IsHumanSender(id) then
    return "You"
  end
  local name = id ~= nil and Civ6Ai_Chat._LeaderName(id) or nil
  if name ~= nil and Locale ~= nil and Locale.Lookup ~= nil then
    local ok, text = pcall(Locale.Lookup, name)
    if ok and text ~= nil and text ~= "" then
      name = text
    end
  end
  return name or ("Player " .. tostring(playerID))
end

function Civ6Ai_Chat._PanelRefresh()
  local c = Civ6Ai_Chat._PanelControls()
  if c == nil then
    return
  end
  c.Civ6AiChatLog:SetText(table.concat(Civ6Ai_Chat._panelLines, "[NEWLINE]"))
  if c.Civ6AiChatScroll ~= nil then
    pcall(function()
      c.Civ6AiChatScroll:CalculateInternalSize()
      c.Civ6AiChatScroll:SetScrollValue(1)
    end)
  end
end

function Civ6Ai_Chat.PanelAdd(line)
  -- Square brackets would be read as markup ([ICON_...], [COLOR...]).
  local clean = string.gsub(tostring(line or ""), "[%[%]]", "")
  if Civ6Ai_Chat._panelLines[1] == Civ6Ai_Chat.PANEL_PLACEHOLDER then
    table.remove(Civ6Ai_Chat._panelLines, 1)
  end
  table.insert(Civ6Ai_Chat._panelLines, clean)
  while #Civ6Ai_Chat._panelLines > Civ6Ai_Chat.PANEL_MAX_LINES do
    table.remove(Civ6Ai_Chat._panelLines, 1)
  end
  Civ6Ai_Chat._PanelRefresh()
end

function Civ6Ai_Chat.PanelOnPublic(fromPlayer, text, turn)
  Civ6Ai_Chat.PanelAdd("T" .. tostring(turn) .. "  " .. Civ6Ai_Chat._PanelName(fromPlayer) .. ": " .. tostring(text))
end

function Civ6Ai_Chat._PanelShowsPrivate(fromPlayer, toPlayer)
  local localPlayer = Game ~= nil and Game.GetLocalPlayer ~= nil and Game.GetLocalPlayer() or -1
  if toPlayer == localPlayer or fromPlayer == localPlayer then
    return true
  end
  return Civ6Ai_Config ~= nil and Civ6Ai_Config.IsHumanSeat ~= nil
    and (Civ6Ai_Config.IsHumanSeat(toPlayer) or Civ6Ai_Config.IsHumanSeat(fromPlayer))
end

function Civ6Ai_Chat.PanelOnPrivate(fromPlayer, toPlayer, text, turn)
  if not Civ6Ai_Chat._PanelShowsPrivate(tonumber(fromPlayer), tonumber(toPlayer)) then
    return
  end
  Civ6Ai_Chat.PanelAdd("T" .. tostring(turn) .. "  " .. Civ6Ai_Chat._PanelName(fromPlayer) .. " to "
    .. Civ6Ai_Chat._PanelName(toPlayer) .. " (private): " .. tostring(text))
end

-- "@Name rest" -> player id of that leader/player name (prefix match), rest.
function Civ6Ai_Chat._PanelTarget(text)
  local name, rest = string.match(text, "^@(%S+)%s+(.+)$")
  if name == nil or PlayerConfigurations == nil then
    return nil, text
  end
  local want = string.lower(name)
  for playerID = 0, 63 do
    local config = PlayerConfigurations[playerID]
    if config ~= nil then
      local leader = Civ6Ai_Chat._PanelName(playerID)
      if string.lower(string.sub(leader, 1, string.len(want))) == want then
        return playerID, rest
      end
    end
  end
  return nil, text
end

function Civ6Ai_Chat.OnPanelInput(text)
  text = tostring(text or "")
  text = string.gsub(text, "^%s+", "")
  text = string.gsub(text, "%s+$", "")
  local c = Civ6Ai_Chat._PanelControls()
  if c ~= nil and c.Civ6AiChatInput ~= nil then
    c.Civ6AiChatInput:SetText("")
  end
  if text == "" then
    return
  end
  local me = Game.GetLocalPlayer()
  local turn = Game.GetCurrentGameTurn()
  local target, body = Civ6Ai_Chat._PanelTarget(text)
  local recipients
  if target ~= nil then
    Civ6Ai_Chat._RecordPrivateChat(me, target, body, turn)
    recipients = Civ6Ai_Chat._ManagedRecipients(target)
  else
    Civ6Ai_Chat._RecordPublicChat(me, text, turn)
    recipients = Civ6Ai_Chat._ManagedRecipients(nil)
  end
  -- In a network game the others also see it in the normal chat.
  if GameConfiguration ~= nil and GameConfiguration.IsNetworkMultiplayer ~= nil
      and GameConfiguration.IsNetworkMultiplayer() and ChatTargetTypes ~= nil then
    if target ~= nil then
      Civ6Ai_Chat._SendNetworkChat(body, ChatTargetTypes.CHATTARGET_PLAYER, target)
    else
      Civ6Ai_Chat._SendNetworkChat(text, ChatTargetTypes.CHATTARGET_ALL, -1)
    end
  end
  local others = {}
  for _, seat in ipairs(recipients or {}) do
    if seat ~= me or target == me then
      others[#others + 1] = seat
    end
  end
  Civ6Ai_Util.Log("chat|panel_input|to=" .. tostring(target or "all") .. "|len=" .. tostring(string.len(text))
    .. "|replies=" .. tostring(#others))
  Civ6Ai_Chat._TriggerAiReplies(others)
end

function Civ6Ai_Chat._PanelSetShown(shown)
  local c = Civ6Ai_Chat._PanelControls()
  if c == nil then
    return
  end
  c.Civ6AiChatRoot:SetHide(not shown)
  if c.Civ6AiChatShow ~= nil then
    c.Civ6AiChatShow:SetHide(shown)
  end
end

function Civ6Ai_Chat.InitPanel()
  local c = Civ6Ai_Chat._PanelControls()
  if c == nil then
    Civ6Ai_Util.Log("chat|panel|missing_controls")
    return false
  end
  if ContextPtr ~= nil and ContextPtr.SetHide ~= nil then
    pcall(function() ContextPtr:SetHide(false) end)
  end
  if c.Civ6AiChatInput ~= nil and c.Civ6AiChatInput.RegisterCommitCallback ~= nil then
    c.Civ6AiChatInput:RegisterCommitCallback(function(text) Civ6Ai_Chat.OnPanelInput(text) end)
  end
  if c.Civ6AiChatToggle ~= nil and Mouse ~= nil then
    c.Civ6AiChatToggle:RegisterCallback(Mouse.eLClick, function() Civ6Ai_Chat._PanelSetShown(false) end)
  end
  if c.Civ6AiChatShow ~= nil and Mouse ~= nil then
    c.Civ6AiChatShow:RegisterCallback(Mouse.eLClick, function() Civ6Ai_Chat._PanelSetShown(true) end)
  end
  -- Refill from this session's history (a reload keeps the chat log file, not
  -- the in-memory lists, so this is what the current Lua state has seen).
  if #Civ6Ai_Chat._panelLines == 0 then
    for _, e in ipairs(Civ6Ai_Chat._publicEvents) do
      local sender = e.affected_ids ~= nil and e.affected_ids[1] or nil
      local id = sender ~= nil and tonumber(string.match(tostring(sender), "(%d+)$")) or nil
      table.insert(Civ6Ai_Chat._panelLines, "T" .. tostring(e.turn) .. "  " .. Civ6Ai_Chat._PanelName(id) .. ": "
        .. string.gsub(tostring(e.text), "[%[%]]", ""))
    end
  end
  if #Civ6Ai_Chat._panelLines == 0 then
    table.insert(Civ6Ai_Chat._panelLines, Civ6Ai_Chat.PANEL_PLACEHOLDER)
  end
  Civ6Ai_Chat._PanelSetShown(true)
  Civ6Ai_Chat._PanelRefresh()
  local w, h = 0, 0
  pcall(function() w, h = UIManager:GetScreenSizeVal() end)
  Civ6Ai_Util.Log("chat|panel|ready|screen=" .. tostring(w) .. "x" .. tostring(h))
  return true
end

function Civ6Ai_Chat.Initialize()
  if Civ6Ai_Chat._initialized then
    return
  end
  Civ6Ai_Chat._initialized = true
  local okPanel, panelErr = pcall(Civ6Ai_Chat.InitPanel)
  if not okPanel then
    Civ6Ai_Util.Log("chat|panel|error|" .. tostring(panelErr))
  end
  if Events ~= nil and Events.LoadGameViewStateDone ~= nil then
    Events.LoadGameViewStateDone.Add(Civ6Ai_Chat._OnLoadGameViewStateDone)
  end
  if Events ~= nil and Events.MultiplayerChat ~= nil then
    Events.MultiplayerChat.Add(Civ6Ai_Chat._OnMultiplayerChat)
  end
  Civ6Ai_Chat._ScheduleWorldTrackerChatEnable()
  Civ6Ai_Util.Log("chat|ready")
end
