-- Civ6Ai hidden inbox: receive apply payloads from the Python sidecar (retail io=false).
Civ6Ai_HostChannel = Civ6Ai_HostChannel or {}

Civ6Ai_HostChannel._applyPending = {}
Civ6Ai_HostChannel._armedUntil = 0

function Civ6Ai_HostChannel._Now()
  if os and os.time then
    return os.time()
  end
  return 0
end

function Civ6Ai_HostChannel._IsArmed()
  return Civ6Ai_HostChannel._Now() <= Civ6Ai_HostChannel._armedUntil
end

function Civ6Ai_HostChannel.Arm(seconds)
  local duration = tonumber(seconds) or 45
  if duration < 5 then
    duration = 5
  end
  Civ6Ai_HostChannel._armedUntil = Civ6Ai_HostChannel._Now() + duration
  Civ6Ai_Util.Log("inbox|armed|" .. tostring(duration))
  Civ6Ai_HostChannel._FocusInbox()
end

function Civ6Ai_HostChannel._FocusInbox()
  if Controls == nil or Controls.HostChannelInput == nil then
    return false
  end
  if Controls.HostChannelInput.TakeKeyboardFocus ~= nil then
    Controls.HostChannelInput:TakeKeyboardFocus()
    return true
  end
  if Controls.HostChannelInput.SetFocus ~= nil then
    Controls.HostChannelInput:SetFocus()
    return true
  end
  return false
end

function Civ6Ai_HostChannel._ClearInbox()
  if Controls ~= nil and Controls.HostChannelInput ~= nil and Controls.HostChannelInput.SetText ~= nil then
    Controls.HostChannelInput:SetText("")
  end
end

function Civ6Ai_HostChannel._ConsumeInboxText()
  if Controls == nil or Controls.HostChannelInput == nil then
    return nil
  end
  local text = Controls.HostChannelInput:GetText()
  if text == nil or text == "" then
    return nil
  end
  Controls.HostChannelInput:SetText("")
  return text
end

function Civ6Ai_HostChannel._SplitLines(text)
  local lines = {}
  for line in string.gmatch(text, "[^\r\n]+") do
    if line ~= "" then
      table.insert(lines, line)
    end
  end
  return lines
end

function Civ6Ai_HostChannel.OnLine(line)
  if line == nil or line == "" then
    return
  end
  if string.find(line, "CIV6AI|host|arm", 1, true) == 1 then
    local seconds = string.match(line, "CIV6AI|host|arm|(%d+)")
    Civ6Ai_HostChannel.Arm(seconds)
    return
  end
  if string.find(line, "CIV6AI|mp_sync_probe|", 1, true) == 1
      or string.find(line, "CIV6AI|mp_move|", 1, true) == 1 then
    if Civ6Ai_MpSync ~= nil and Civ6Ai_MpSync.HandleWireText ~= nil then
      Civ6Ai_MpSync.HandleWireText(line, "host_inbox")
    else
      Civ6Ai_Util.Log("inbox|mp_sync_unavailable")
    end
    return
  end
  if string.find(line, "CIV6AI|apply|begin|", 1, true) == 1 then
    local id, chunks, player, turn, session = string.match(
      line,
      "^CIV6AI|apply|begin|([^|]+)|(%d+)|(%d+)|(-?%d+)|(.*)$"
    )
    if id ~= nil then
      Civ6Ai_HostChannel._applyPending[id] = {
        id = id,
        chunks = tonumber(chunks) or 1,
        player = tonumber(player) or 0,
        turn = tonumber(turn) or 0,
        session = session or "",
        parts = {},
      }
      Civ6Ai_Util.Log("inbox|apply_begin|" .. id .. "|player=" .. tostring(player))
    end
    return
  end
  if string.find(line, "CIV6AI|apply|c|", 1, true) == 1 then
    local id, index, data = string.match(line, "^CIV6AI|apply|c|([^|]+)|(%d+)|(.*)$")
    local blob = Civ6Ai_HostChannel._applyPending[id]
    if blob ~= nil and index ~= nil then
      blob.parts[tonumber(index) or 0] = data or ""
    end
    return
  end
  if string.find(line, "CIV6AI|apply|end|", 1, true) == 1 then
    local id = string.match(line, "^CIV6AI|apply|end|([^|]+)$")
    local blob = Civ6Ai_HostChannel._applyPending[id]
    Civ6Ai_HostChannel._applyPending[id] = nil
    if blob == nil then
      Civ6Ai_Util.Log("inbox|apply_end_missing|" .. tostring(id))
      return
    end
    local sessionId = Civ6Ai_Bridge.SessionId()
    if blob.session ~= nil and blob.session ~= "" and blob.session ~= sessionId then
      Civ6Ai_Util.Log(
        "inbox|apply_stale_session|expected="
          .. tostring(sessionId)
          .. "|got="
          .. tostring(blob.session)
      )
      return
    end
    local turn = Game.GetCurrentGameTurn()
    local pieces = {}
    for i = 0, blob.chunks - 1 do
      table.insert(pieces, blob.parts[i] or "")
    end
    local encoded = table.concat(pieces, "")
    local decoded = Civ6Ai_Util.Base64Decode(encoded)
    if decoded == nil or decoded == "" then
      Civ6Ai_Util.Log("inbox|apply_decode_failed|" .. blob.id)
      return
    end
    Civ6Ai_Util.Log(
      "inbox|apply_ready|player="
        .. tostring(blob.player)
        .. "|turn="
        .. tostring(turn)
        .. "|len="
        .. tostring(string.len(decoded))
    )
    Civ6Ai_Bridge.ApplyPayload(blob.player, decoded)
    return
  end
end

function Civ6Ai_HostChannel._IsCompleteWireLine(text)
  if text == nil or text == "" then
    return false
  end
  if string.find(text, "\r", 1, true) or string.find(text, "\n", 1, true) then
    return false
  end
  if string.find(text, "CIV6AI|host|arm|", 1, true) == 1 then
    return string.match(text, "^CIV6AI|host|arm|(%d+)$") ~= nil
  end
  if string.find(text, "CIV6AI|mp_sync_probe|", 1, true) == 1 then
    return string.match(text, "^CIV6AI|mp_sync_probe|(%-?%d+)|(%-?%d+)|(%-?%d+)|(%-?%d+)$") ~= nil
  end
  if string.find(text, "CIV6AI|mp_move|", 1, true) == 1 then
    return string.match(text, "^CIV6AI|mp_move|([^|]+)|(%-?%d+)|(%-?%d+)|(%-?%d+)|(%-?%d+)$") ~= nil
  end
  if string.find(text, "CIV6AI|apply|begin|", 1, true) == 1 then
    return string.match(text, "^CIV6AI|apply|begin|([^|]+)|(%d+)|(%d+)|(-?%d+)|(.*)$") ~= nil
  end
  if string.find(text, "CIV6AI|apply|c|", 1, true) == 1 then
    return string.match(text, "^CIV6AI|apply|c|([^|]+)|(%d+)|(.*)$") ~= nil
  end
  if string.find(text, "CIV6AI|apply|end|", 1, true) == 1 then
    return string.match(text, "^CIV6AI|apply|end|([^|]+)$") ~= nil
  end
  return false
end

function Civ6Ai_HostChannel._DeliverInboxText(text)
  if text == nil or text == "" then
    return false
  end
  Civ6Ai_HostChannel._OnInboxText(text)
  Civ6Ai_HostChannel._ClearInbox()
  return true
end

function Civ6Ai_HostChannel.CommitLine(line)
  if line == nil or line == "" then
    return false
  end
  Civ6Ai_HostChannel.OnLine(line)
  return true
end

function Civ6Ai_HostChannel._OnInboxStringChanged()
  if Controls == nil or Controls.HostChannelInput == nil then
    return
  end
  local text = Controls.HostChannelInput:GetText()
  if not Civ6Ai_HostChannel._IsCompleteWireLine(text) then
    return
  end
  Civ6Ai_HostChannel._DeliverInboxText(text)
end

function Civ6Ai_HostChannel._OnInboxText(text)
  if text == nil or text == "" then
    return
  end
  if string.find(text, "CIV6AI|", 1, true) ~= 1 then
    return
  end
  Civ6Ai_Util.Log("inbox|text|len=" .. tostring(string.len(text)))
  for _, line in ipairs(Civ6Ai_HostChannel._SplitLines(text)) do
    Civ6Ai_HostChannel.OnLine(line)
  end
end

function Civ6Ai_HostChannel._OnHostChannelCommit()
  local text = Civ6Ai_HostChannel._ConsumeInboxText()
  if text ~= nil then
    Civ6Ai_HostChannel._OnInboxText(text)
  end
end

function Civ6Ai_HostChannel.Poll()
  if not Civ6Ai_HostChannel._IsArmed() then
    return
  end
  if Controls == nil or Controls.HostChannelInput == nil or Controls.HostChannelInput.GetText == nil then
    return
  end
  local text = Controls.HostChannelInput:GetText()
  if text ~= nil and text ~= "" and string.find(text, "CIV6AI|", 1, true) ~= nil then
    Civ6Ai_HostChannel._DeliverInboxText(text)
    return
  end
  if text == nil or text == "" then
    Civ6Ai_HostChannel._FocusInbox()
  end
end

function Civ6Ai_HostChannel._WireInbox()
  if Civ6Ai_HostChannel._inboxWired then
    return true
  end
  if Controls == nil or Controls.HostChannelInput == nil then
    return false
  end
  if Controls.HostChannelInput.SetHide ~= nil then
    local hideInbox = not (Civ6Ai_Config ~= nil and Civ6Ai_Config.IsAutotest ~= nil and Civ6Ai_Config.IsAutotest())
    Controls.HostChannelInput:SetHide(hideInbox)
  end
  if InputTriggerTypes ~= nil and InputTriggerTypes.EditBoxCommit ~= nil then
    Controls.HostChannelInput:RegisterCallback(InputTriggerTypes.EditBoxCommit, Civ6Ai_HostChannel._OnHostChannelCommit)
  end
  if InputTriggerTypes ~= nil and InputTriggerTypes.EditBoxStringChanged ~= nil then
    -- Paste delivers a full wire line in one event; ignore partial keystrokes via _IsCompleteWireLine.
    Controls.HostChannelInput:RegisterCallback(InputTriggerTypes.EditBoxStringChanged, Civ6Ai_HostChannel._OnInboxStringChanged)
  end
  Civ6Ai_HostChannel._inboxWired = true
  Civ6Ai_Util.Log("inbox|editbox|ready")
  return true
end

function Civ6Ai_HostChannel.Initialize()
  if Civ6Ai_HostChannel._initialized then
    return
  end
  Civ6Ai_HostChannel._initialized = true
  ExposedMembers = ExposedMembers or {}
  ExposedMembers.Civ6Ai = ExposedMembers.Civ6Ai or {}
  ExposedMembers.Civ6Ai.ReceiveHostLine = Civ6Ai_HostChannel.OnLine
  ExposedMembers.Civ6Ai.CommitHostLine = Civ6Ai_HostChannel.CommitLine
  ExposedMembers.Civ6Ai.ArmHostInbox = Civ6Ai_HostChannel.Arm
  ExposedMembers.Civ6Ai.FocusHostInbox = Civ6Ai_HostChannel._FocusInbox
  if not Civ6Ai_HostChannel._WireInbox() then
    if Events ~= nil and Events.LoadGameViewStateDone ~= nil then
      Events.LoadGameViewStateDone.Add(Civ6Ai_HostChannel._WireInbox)
    end
  end
  Civ6Ai_Util.Log("inbox|ready")
end
