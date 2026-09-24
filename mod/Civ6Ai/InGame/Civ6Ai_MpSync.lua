-- Civ6Ai MP move sync (M2): broadcast move intent; every client executes the same GameCore move.
-- Flag: CIV6AI_MP_MOVE_SYNC=1 (GameConfiguration / Civ6Ai_Paths.MpMoveSync / Runtime.MpMoveSync).
-- Transport: Network.SendChat + Events.MultiplayerChat → ExposedMembers.Civ6Ai.MoveUnitForPlayer.
-- Untested in-game / LAN — see docs/MP_SYNC_TRANSPORT.md.
Civ6Ai_MpSync = Civ6Ai_MpSync or {}

Civ6Ai_MpSync._PREFIX = "CIV6AI|mp_move|"
Civ6Ai_MpSync._PROBE_PREFIX = "CIV6AI|mp_sync_probe|"
Civ6Ai_MpSync._seen = Civ6Ai_MpSync._seen or {}
Civ6Ai_MpSync._seq = Civ6Ai_MpSync._seq or 0
Civ6Ai_MpSync._maxSeen = 256

function Civ6Ai_MpSync._IsNetworkMultiplayer()
  if Civ6Ai_Apply ~= nil and Civ6Ai_Apply._IsNetworkMultiplayer ~= nil then
    return Civ6Ai_Apply._IsNetworkMultiplayer()
  end
  if GameConfiguration ~= nil and GameConfiguration.IsNetworkMultiplayer ~= nil then
    return GameConfiguration.IsNetworkMultiplayer()
  end
  return false
end

function Civ6Ai_MpSync.IsEnabled()
  if Civ6Ai_Config ~= nil and Civ6Ai_Config.IsMpMoveSync ~= nil then
    return Civ6Ai_Config.IsMpMoveSync()
  end
  if GameConfiguration ~= nil and GameConfiguration.GetValue ~= nil then
    if GameConfiguration.GetValue("CIV6AI_MP_MOVE_SYNC") == 1 then
      return true
    end
  end
  if Civ6Ai_Paths ~= nil and tonumber(Civ6Ai_Paths.MpMoveSync) == 1 then
    return true
  end
  return false
end

function Civ6Ai_MpSync.IsActive()
  return Civ6Ai_MpSync.IsEnabled() and Civ6Ai_MpSync._IsNetworkMultiplayer()
end

function Civ6Ai_MpSync._Remember(seq)
  if seq == nil or seq == "" then
    return false
  end
  if Civ6Ai_MpSync._seen[seq] then
    return true
  end
  Civ6Ai_MpSync._seen[seq] = true
  local count = 0
  for _ in pairs(Civ6Ai_MpSync._seen) do
    count = count + 1
  end
  if count > Civ6Ai_MpSync._maxSeen then
    Civ6Ai_MpSync._seen = { [seq] = true }
  end
  return false
end

function Civ6Ai_MpSync._NextSeq()
  Civ6Ai_MpSync._seq = Civ6Ai_MpSync._seq + 1
  local turn = 0
  if Game ~= nil and Game.GetCurrentGameTurn ~= nil then
    turn = Game.GetCurrentGameTurn() or 0
  end
  local host = 0
  if Game ~= nil and Game.GetLocalPlayer ~= nil then
    host = Game.GetLocalPlayer() or 0
  end
  return tostring(turn) .. "." .. tostring(host) .. "." .. tostring(Civ6Ai_MpSync._seq)
end

function Civ6Ai_MpSync._EncodeMove(seq, playerID, unitNumericId, x, y)
  return Civ6Ai_MpSync._PREFIX
    .. tostring(seq)
    .. "|"
    .. tostring(playerID)
    .. "|"
    .. tostring(unitNumericId)
    .. "|"
    .. tostring(x)
    .. "|"
    .. tostring(y)
end

function Civ6Ai_MpSync._ParseMove(text)
  if text == nil or text == "" then
    return nil
  end
  local seq, playerID, unitId, x, y = string.match(
    text,
    "^CIV6AI|mp_move|([^|]+)|(%-?%d+)|(%-?%d+)|(%-?%d+)|(%-?%d+)$"
  )
  if seq == nil then
    return nil
  end
  return {
    seq = seq,
    playerID = tonumber(playerID),
    unitNumericId = tonumber(unitId),
    x = tonumber(x),
    y = tonumber(y),
  }
end

function Civ6Ai_MpSync._ParseProbe(text)
  if text == nil or text == "" then
    return nil
  end
  local playerID, unitId, x, y = string.match(
    text,
    "^CIV6AI|mp_sync_probe|(%-?%d+)|(%-?%d+)|(%-?%d+)|(%-?%d+)$"
  )
  if playerID == nil then
    return nil
  end
  return {
    playerID = tonumber(playerID),
    unitNumericId = tonumber(unitId),
    x = tonumber(x),
    y = tonumber(y),
  }
end

function Civ6Ai_MpSync._SendChat(text)
  if Network == nil or Network.SendChat == nil then
    return false, "network_sendchat_unavailable"
  end
  if ChatTargetTypes == nil then
    return false, "chat_target_types_unavailable"
  end
  Network.SendChat(text, ChatTargetTypes.CHATTARGET_ALL, -1)
  return true, ""
end

function Civ6Ai_MpSync.ExecuteMove(seq, playerID, unitNumericId, x, y, source)
  if Civ6Ai_MpSync._Remember(seq) then
    Civ6Ai_Util.Log(
      "apply|mp_sync|dedup|seq="
        .. tostring(seq)
        .. "|source="
        .. tostring(source or "")
    )
    return true, "dedup"
  end
  if ExposedMembers == nil or ExposedMembers.Civ6Ai == nil or ExposedMembers.Civ6Ai.MoveUnitForPlayer == nil then
    Civ6Ai_Util.Log("apply|mp_sync|exec|fail|gamecore_unavailable|seq=" .. tostring(seq))
    return false, "gamecore_unavailable"
  end
  local ok, reason = ExposedMembers.Civ6Ai.MoveUnitForPlayer(playerID, unitNumericId, x, y)
  if ok then
    Civ6Ai_Util.Log(
      "apply|mp_sync|exec|ok|player="
        .. tostring(playerID)
        .. "|unit="
        .. tostring(unitNumericId)
        .. "|plot="
        .. tostring(x)
        .. ","
        .. tostring(y)
        .. "|seq="
        .. tostring(seq)
        .. "|source="
        .. tostring(source or "")
    )
    return true, ""
  end
  Civ6Ai_Util.Log(
    "apply|mp_sync|exec|fail|player="
      .. tostring(playerID)
      .. "|reason="
      .. tostring(reason or "rejected")
      .. "|seq="
      .. tostring(seq)
      .. "|source="
      .. tostring(source or "")
  )
  return false, reason or "mp_sync_exec_rejected"
end

function Civ6Ai_MpSync.BroadcastMove(playerID, unitNumericId, x, y)
  local seq = Civ6Ai_MpSync._NextSeq()
  local wire = Civ6Ai_MpSync._EncodeMove(seq, playerID, unitNumericId, x, y)
  Civ6Ai_Util.Log(
    "apply|mp_sync|enqueue|player="
      .. tostring(playerID)
      .. "|unit="
      .. tostring(unitNumericId)
      .. "|plot="
      .. tostring(x)
      .. ","
      .. tostring(y)
      .. "|seq="
      .. tostring(seq)
  )
  local sent, sendReason = Civ6Ai_MpSync._SendChat(wire)
  if not sent then
    Civ6Ai_Util.Log("apply|mp_sync|enqueue|fail|" .. tostring(sendReason))
    return false, sendReason
  end
  -- Host executes immediately; MultiplayerChat echo is deduped by seq.
  local ok, reason = Civ6Ai_MpSync.ExecuteMove(seq, playerID, unitNumericId, x, y, "host_local")
  if ok then
    return true, ""
  end
  return false, reason or "mp_sync_host_exec_failed"
end

function Civ6Ai_MpSync.HandleWireText(text, source)
  if text == nil or text == "" then
    return false
  end
  local probe = Civ6Ai_MpSync._ParseProbe(text)
  if probe ~= nil then
    Civ6Ai_Util.Log(
      "apply|mp_sync|probe|player="
        .. tostring(probe.playerID)
        .. "|unit="
        .. tostring(probe.unitNumericId)
        .. "|plot="
        .. tostring(probe.x)
        .. ","
        .. tostring(probe.y)
        .. "|source="
        .. tostring(source or "")
    )
    local seq = "probe." .. tostring(probe.playerID) .. "." .. tostring(probe.unitNumericId)
      .. "." .. tostring(probe.x) .. "." .. tostring(probe.y)
    local ok = Civ6Ai_MpSync.ExecuteMove(
      seq,
      probe.playerID,
      probe.unitNumericId,
      probe.x,
      probe.y,
      source or "probe"
    )
    return ok
  end
  local move = Civ6Ai_MpSync._ParseMove(text)
  if move == nil then
    return false
  end
  Civ6Ai_MpSync.ExecuteMove(
    move.seq,
    move.playerID,
    move.unitNumericId,
    move.x,
    move.y,
    source or "chat"
  )
  return true
end

function Civ6Ai_MpSync._OnMultiplayerChat(fromPlayer, toPlayer, text, eTargetType)
  if text == nil or text == "" then
    return
  end
  if string.find(text, Civ6Ai_MpSync._PREFIX, 1, true) == 1
      or string.find(text, Civ6Ai_MpSync._PROBE_PREFIX, 1, true) == 1 then
    if not Civ6Ai_MpSync.IsEnabled() then
      Civ6Ai_Util.Log("apply|mp_sync|ignored|flag_off")
      return
    end
    Civ6Ai_MpSync.HandleWireText(text, "multiplayer_chat")
  end
end

function Civ6Ai_MpSync.Initialize()
  if Civ6Ai_MpSync._initialized then
    return
  end
  Civ6Ai_MpSync._initialized = true
  if Events ~= nil and Events.MultiplayerChat ~= nil then
    Events.MultiplayerChat.Add(Civ6Ai_MpSync._OnMultiplayerChat)
  end
  Civ6Ai_Util.Log(
    "mp_sync|ready|enabled="
      .. tostring(Civ6Ai_MpSync.IsEnabled())
      .. "|active="
      .. tostring(Civ6Ai_MpSync.IsActive())
  )
end
