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
  if Civ6Ai_Chat._restoring then
    return
  end
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
  local body = string.gsub(tostring(text or ""), "[\r\n|]", " ")
  Civ6Ai_Chat._AppendReplay("A|" .. tostring(turn) .. "|" .. tostring(fromPlayer) .. "|" .. body)
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
  local body = string.gsub(tostring(text or ""), "[\r\n|]", " ")
  Civ6Ai_Chat._AppendReplay(
    "P|" .. tostring(turn) .. "|" .. tostring(fromPlayer) .. "|" .. tostring(toPlayer) .. "|" .. body
  )
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
  -- A "Leader: body" line was sent as this network account for another seat.
  -- Record and show that seat. Only a real human line asks the models to reply.
  local speaker, body = Civ6Ai_Chat._ParseWire(text)
  local relay = speaker ~= nil and speaker ~= fromPlayer
  if relay then
    fromPlayer = speaker
    text = body
  end
  if not relay and not Civ6Ai_Chat._IsHumanSender(fromPlayer) then
    return
  end
  local turn = Game.GetCurrentGameTurn()
  local recipients = {}
  if Civ6Ai_Chat._IsPrivateTarget(toPlayer, eTargetType) then
    local target = tonumber(toPlayer)
    Civ6Ai_Chat._RecordPrivateChat(fromPlayer, target, text, turn)
    if not relay and fromPlayer == Game.GetLocalPlayer() then
    end
    if not relay then
      recipients = Civ6Ai_Chat._ManagedRecipients(target)
    end
    Civ6Ai_Util.Log(
      "chat|human_private|from=" .. tostring(fromPlayer) .. "|to=" .. tostring(target) .. "|len=" .. tostring(string.len(text))
    )
  else
    Civ6Ai_Chat._RecordPublicChat(fromPlayer, text, turn)
    if not relay and fromPlayer == Game.GetLocalPlayer() then
    end
    if not relay then
      recipients = Civ6Ai_Chat._ManagedRecipients(nil)
    end
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

-- Display name used on the wire and in the custom panel. Never "You": every
-- machine must parse the same string back to a player id.
function Civ6Ai_Chat._SpeakerName(playerID)
  local name = Civ6Ai_Chat._LeaderName(playerID)
  if name ~= nil and Locale ~= nil and Locale.Lookup ~= nil then
    local ok, text = pcall(Locale.Lookup, name)
    if ok and text ~= nil and text ~= "" then
      name = text
    end
  end
  if name == nil or name == "" then
    return nil
  end
  return name
end

-- Network.SendChat always attributes the line to the local network player
-- (Firaxis ChatPanel.lua OnChat uses PlayerConfigurations[fromPlayer]:GetPlayerName()).
-- Seats other than that account prefix the body with their speaker name. The
-- custom panel and the model log parse it back off and store the real seat.
function Civ6Ai_Chat._WireText(senderPlayerID, text)
  text = tostring(text or "")
  if Game ~= nil and Game.GetLocalPlayer ~= nil and senderPlayerID == Game.GetLocalPlayer() then
    return text
  end
  local name = Civ6Ai_Chat._SpeakerName(senderPlayerID)
  if name == nil then
    return text
  end
  return name .. ": " .. text
end

function Civ6Ai_Chat._ParseWire(text)
  text = tostring(text or "")
  if PlayerConfigurations == nil then
    return nil, text
  end
  local bestId, bestLen = nil, 0
  for playerID, config in pairs(PlayerConfigurations) do
    if type(playerID) == "number" and config ~= nil then
      local name = Civ6Ai_Chat._SpeakerName(playerID)
      local prefix = name ~= nil and (name .. ": ") or nil
      if prefix ~= nil and string.sub(text, 1, string.len(prefix)) == prefix and string.len(prefix) > bestLen then
        bestId = playerID
        bestLen = string.len(prefix)
      end
    end
  end
  if bestId == nil then
    return nil, text
  end
  return bestId, string.sub(text, bestLen + 1)
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
  local wire = Civ6Ai_Chat._WireText(senderPlayerID, text)
  local target = tostring(message.target or "all")
  if target == "all" or target == "public" then
    if Civ6Ai_Chat._SendNetworkChat(wire, ChatTargetTypes.CHATTARGET_ALL, -1) then
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
    if Civ6Ai_Chat._SendNetworkChat(wire, ChatTargetTypes.CHATTARGET_PLAYER, targetPlayer) then
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
  local name = Civ6Ai_Chat._SpeakerName(playerID)
  return name or ("Player " .. tostring(playerID))
end

function Civ6Ai_Chat._PlainChat(text)
  return string.gsub(tostring(text or ""), "[%[%]]", "")
end

-- Same tags the World Tracker chat uses: speaker name, then the message.
function Civ6Ai_Chat._PanelLine(turn, fromPlayer, toPlayer, text)
  local name = Civ6Ai_Chat._PlainChat(Civ6Ai_Chat._PanelName(fromPlayer))
  local head = "[color:ChatPlayerName]" .. name
  if toPlayer ~= nil then
    head = head .. " [" .. Civ6Ai_Chat._PlainChat(Civ6Ai_Chat._PanelName(toPlayer)) .. "]"
  end
  local tone = toPlayer ~= nil and "[color:ChatMessage_Whisper]" or "[color:ChatMessage_Global]"
  return "T" .. tostring(turn) .. "  " .. head .. ": [ENDCOLOR]" .. tone
    .. Civ6Ai_Chat._PlainChat(text) .. " [ENDCOLOR]"
end

function Civ6Ai_Chat._ChatEntry()
  local c = Civ6Ai_Chat._PanelControls()
  if c == nil then
    return nil
  end
  if c.Civ6AiChatInput ~= nil then
    return c.Civ6AiChatInput
  end
  return c.ChatEntry
end

function Civ6Ai_Chat._TargetCaption()
  if Civ6Ai_Chat._panelTarget == nil then
    return "To All", "[ICON_Global]"
  end
  return "To " .. Civ6Ai_Chat._PanelName(Civ6Ai_Chat._panelTarget), "[ICON_Whisper]"
end

function Civ6Ai_Chat._ShowTargetIcon()
  local c = Civ6Ai_Chat._PanelControls()
  if c == nil then
    return
  end
  local caption, icon = Civ6Ai_Chat._TargetCaption()
  if c.Civ6AiChatTargetIcon ~= nil then
    c.Civ6AiChatTargetIcon:SetText(icon)
  end
  if c.Civ6AiChatTargetLabel ~= nil then
    c.Civ6AiChatTargetLabel:SetText(caption)
  end
end

function Civ6Ai_Chat._HasMet(otherID)
  local me = Game ~= nil and Game.GetLocalPlayer ~= nil and Game.GetLocalPlayer() or nil
  if me == nil or otherID == nil or otherID == me or Players == nil or Players[me] == nil then
    return false
  end
  local other = Players[otherID]
  if other == nil then
    return false
  end
  if other.IsAlive ~= nil and not other:IsAlive() then
    return false
  end
  if PlayerConfigurations ~= nil and PlayerConfigurations[otherID] ~= nil
      and PlayerConfigurations[otherID].GetCivilizationTypeName ~= nil then
    local civ = PlayerConfigurations[otherID]:GetCivilizationTypeName()
    if civ == "CIVILIZATION_BARBARIAN" or civ == "CIVILIZATION_FREE_CITIES" then
      return false
    end
  end
  local diplo = Players[me].GetDiplomacy ~= nil and Players[me]:GetDiplomacy() or nil
  return diplo ~= nil and diplo.HasMet ~= nil and diplo:HasMet(otherID) == true
end

function Civ6Ai_Chat._FillTargetPull()
  local c = Civ6Ai_Chat._PanelControls()
  local pull = c ~= nil and c.Civ6AiChatPull or nil
  if pull == nil or pull.ClearEntries == nil or pull.BuildEntry == nil then
    Civ6Ai_Util.Log("chat|panel|target_pull_missing")
    return
  end
  pull:ClearEntries()
  local function add(label, icon, targetId)
    local row = {}
    pull:BuildEntry("InstanceOne", row)
    if row.Button ~= nil then
      if row.Button.SetText ~= nil then
        row.Button:SetText(label)
      end
      if row.Button.SetVoids ~= nil then
        row.Button:SetVoids(targetId == nil and -1 or targetId, 0)
      end
    end
    if row.ChatIcon ~= nil then
      row.ChatIcon:SetText(icon)
    end
  end
  add("To All", "[ICON_Global]", nil)
  if PlayerConfigurations ~= nil then
    for playerID = 0, 63 do
      if PlayerConfigurations[playerID] ~= nil and Civ6Ai_Chat._HasMet(playerID) then
        add("To " .. Civ6Ai_Chat._PanelName(playerID), "[ICON_Whisper]", playerID)
      end
    end
  end
  local keep = Civ6Ai_Chat._panelTarget
  if keep ~= nil and not Civ6Ai_Chat._HasMet(keep) then
    keep = nil
  end
  if pull.RegisterSelectionCallback ~= nil then
    pull:RegisterSelectionCallback(function(targetId)
      if targetId == nil or targetId < 0 then
        Civ6Ai_Chat._panelTarget = nil
      else
        Civ6Ai_Chat._panelTarget = targetId
      end
      Civ6Ai_Chat._ShowTargetIcon()
    end)
  end
  if pull.CalculateInternals ~= nil then
    pull:CalculateInternals()
  end
  Civ6Ai_Chat._panelTarget = keep
  Civ6Ai_Chat._ShowTargetIcon()
end

function Civ6Ai_Chat._ReplayPath()
  if Civ6Ai_Bridge == nil or Civ6Ai_Bridge._SessionDir == nil then
    return nil
  end
  return Civ6Ai_Util.JoinPath(Civ6Ai_Bridge._SessionDir(), "chat_replay.txt")
end

function Civ6Ai_Chat._AppendReplay(line)
  if Civ6Ai_Chat._restoring then
    return
  end
  local path = Civ6Ai_Chat._ReplayPath()
  if path == nil then
    return
  end
  Civ6Ai_Util.AppendTextLine(path, line)
end

function Civ6Ai_Chat._ApplySavedLine(line)
  local kind, turn, fromId, rest = string.match(tostring(line or ""), "^(%a)|(%d+)|(%d+)|(.*)$")
  if kind == nil then
    return
  end
  turn = tonumber(turn)
  fromId = tonumber(fromId)
  if kind == "A" then
    Civ6Ai_Chat._RecordPublicChat(fromId, rest, turn)
    return
  end
  local toId, text = string.match(rest, "^(%d+)|(.*)$")
  if kind == "P" and toId ~= nil then
    Civ6Ai_Chat._RecordPrivateChat(fromId, tonumber(toId), text, turn)
  end
end

function Civ6Ai_Chat.Restore()
  local path = Civ6Ai_Chat._ReplayPath()
  local blob = path ~= nil and Civ6Ai_Util.ReadTextFile(path) or nil
  if blob == nil or blob == "" then
    return
  end
  Civ6Ai_Chat._restoring = true
  Civ6Ai_Chat._publicEvents = {}
  Civ6Ai_Chat._privateInbox = {}
  Civ6Ai_Chat._panelLines = {}
  local count = 0
  for line in string.gmatch(blob, "[^\n]+") do
    if string.sub(line, 1, 2) == "A|" or string.sub(line, 1, 2) == "P|" then
      Civ6Ai_Chat._ApplySavedLine(line)
      count = count + 1
    end
  end
  Civ6Ai_Chat._restoring = false
  if count > 0 then
    Civ6Ai_Util.Log("chat|restored|lines=" .. tostring(count))
  end
end

Civ6Ai_Chat.PANEL_MIN_W = 360
Civ6Ai_Chat.PANEL_MIN_H = 180

function Civ6Ai_Chat._Clamp(value, low, high)
  if value < low then
    return low
  end
  if value > high then
    return high
  end
  return value
end

function Civ6Ai_Chat._ApplyPanelSize(width, height)
  local c = Civ6Ai_Chat._PanelControls()
  if c == nil or c.Civ6AiChatRoot == nil then
    return
  end
  local maxW, maxH = 1600, 1000
  if UIManager ~= nil and UIManager.GetScreenSizeVal ~= nil then
    local screenW, screenH = UIManager:GetScreenSizeVal()
    if type(screenW) == "number" and screenW > 80 then
      maxW = screenW - 40
    end
    if type(screenH) == "number" and screenH > 80 then
      maxH = screenH - 40
    end
  end
  width = Civ6Ai_Chat._Clamp(width, Civ6Ai_Chat.PANEL_MIN_W, maxW)
  height = Civ6Ai_Chat._Clamp(height, Civ6Ai_Chat.PANEL_MIN_H, maxH)
  c.Civ6AiChatRoot:SetSizeX(width)
  c.Civ6AiChatRoot:SetSizeY(height)
  local scrollW = width - 24
  local scrollH = height - 74
  if c.Civ6AiChatScroll ~= nil then
    c.Civ6AiChatScroll:SetSizeX(scrollW)
    c.Civ6AiChatScroll:SetSizeY(scrollH)
    pcall(function() c.Civ6AiChatScroll:CalculateInternalSize() end)
  end
  if c.Civ6AiChatLog ~= nil and c.Civ6AiChatLog.SetWrapWidth ~= nil then
    c.Civ6AiChatLog:SetWrapWidth(scrollW - 26)
  end
  if c.Civ6AiChatInputRow ~= nil then
    c.Civ6AiChatInputRow:SetSizeX(width - 20)
  end
  if c.Civ6AiChatInputBox ~= nil then
    c.Civ6AiChatInputBox:SetSizeX(width - 20 - 174)
  end
end

function Civ6Ai_Chat._OnDragResize()
  local c = Civ6Ai_Chat._PanelControls()
  if c == nil or c.Civ6AiChatRoot == nil or UIManager == nil or UIManager.GetMousePos == nil then
    return
  end
  local mouseX, mouseY = UIManager:GetMousePos()
  if Civ6Ai_Chat._drag == nil then
    Civ6Ai_Chat._drag = {
      mouseX = mouseX,
      mouseY = mouseY,
      width = c.Civ6AiChatRoot:GetSizeX(),
      height = c.Civ6AiChatRoot:GetSizeY(),
    }
  end
  -- The panel is anchored on the left and vertical center, so a height change
  -- moves the bottom corner by half that amount.
  Civ6Ai_Chat._ApplyPanelSize(
    Civ6Ai_Chat._drag.width + (mouseX - Civ6Ai_Chat._drag.mouseX),
    Civ6Ai_Chat._drag.height + 2 * (mouseY - Civ6Ai_Chat._drag.mouseY)
  )
end

function Civ6Ai_Chat._OnPanelInput(input)
  if input == nil or input.GetMessageType == nil or MouseEvents == nil then
    return false
  end
  local message = input:GetMessageType()
  if message == MouseEvents.LButtonUp or message == MouseEvents.PointerUp then
    Civ6Ai_Chat._drag = nil
  end
  return false
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
  local clean = tostring(line or "")
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
  Civ6Ai_Chat.PanelAdd(Civ6Ai_Chat._PanelLine(turn, fromPlayer, nil, text))
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
  Civ6Ai_Chat.PanelAdd(Civ6Ai_Chat._PanelLine(turn, fromPlayer, toPlayer, text))
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
  text = Civ6Ai_Util.TrimAsciiWSLeft(text)
  text = Civ6Ai_Util.TrimAsciiWSRight(text)
  local entry = Civ6Ai_Chat._ChatEntry()
  if entry ~= nil then
    if entry.ClearString ~= nil then
      entry:ClearString()
    elseif entry.SetText ~= nil then
      entry:SetText("")
    end
  end
  if text == "" then
    return
  end
  local me = Game.GetLocalPlayer()
  local turn = Game.GetCurrentGameTurn()
  local target = Civ6Ai_Chat._panelTarget
  if target ~= nil and not Civ6Ai_Chat._HasMet(target) then
    target = nil
  end
  local typedTarget, body = Civ6Ai_Chat._PanelTarget(text)
  if typedTarget ~= nil and Civ6Ai_Chat._HasMet(typedTarget) then
    target = typedTarget
    text = body
  end
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
  local entry = Civ6Ai_Chat._ChatEntry()
  if entry ~= nil and entry.RegisterCommitCallback ~= nil then
    entry:RegisterCommitCallback(function(text) Civ6Ai_Chat.OnPanelInput(text) end)
  end
  Civ6Ai_Chat._FillTargetPull()
  if c.Civ6AiChatDragSizer ~= nil and Drag ~= nil and Drag.eDrag ~= nil then
    c.Civ6AiChatDragSizer:RegisterCallback(Drag.eDrag, Civ6Ai_Chat._OnDragResize)
  end
  if ContextPtr ~= nil and ContextPtr.SetInputHandler ~= nil then
    ContextPtr:SetInputHandler(Civ6Ai_Chat._OnPanelInput, true)
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
      table.insert(Civ6Ai_Chat._panelLines, Civ6Ai_Chat._PanelLine(e.turn, id, nil, e.text))
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
  if Events ~= nil and Events.LocalPlayerTurnBegin ~= nil then
    Events.LocalPlayerTurnBegin.Add(function()
      Civ6Ai_Chat._FillTargetPull()
    end)
  end
  if Events ~= nil and Events.MultiplayerChat ~= nil then
    Events.MultiplayerChat.Add(Civ6Ai_Chat._OnMultiplayerChat)
  end
  Civ6Ai_Chat._ScheduleWorldTrackerChatEnable()
  Civ6Ai_Util.Log("chat|ready")
end
