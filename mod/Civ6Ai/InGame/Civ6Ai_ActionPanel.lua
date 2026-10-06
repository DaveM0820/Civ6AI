-- Civ6Ai: gate a human host's End Turn until AI seats have answered
-- (same barrier as autotest). Separate Lua context from InGame, so all
-- calls go through ExposedMembers.Civ6Ai / pcall. Vanilla APIs that may
-- not exist are never assumed.

if not pcall(function() include("ActionPanel_Expansion2"); end) then
  if not pcall(function() include("ActionPanel_Expansion1"); end) then
    include("ActionPanel");
  end
end

local BASE_OnEndTurnClicked = OnEndTurnClicked;
local BASE_DoEndTurn = DoEndTurn;

local function _shared()
  return ExposedMembers ~= nil and ExposedMembers.Civ6Ai or nil;
end

local function _try_hold_end_turn()
  local shared = _shared();
  if shared == nil or shared.RequestHostEndTurn == nil then
    return false;
  end
  local ok, held = pcall(shared.RequestHostEndTurn);
  return ok and held == true;
end

local function _waiting_status()
  local shared = _shared();
  if shared == nil then
    return false, "";
  end
  local waiting, status = false, "";
  if shared.HostEndTurnWaiting ~= nil then
    local ok, value = pcall(shared.HostEndTurnWaiting);
    waiting = ok and value == true;
  end
  if shared.HostEndTurnStatus ~= nil then
    local ok, value = pcall(shared.HostEndTurnStatus);
    if ok and value ~= nil then
      status = tostring(value);
    end
  end
  return waiting, status;
end

local function _show_waiting_ui(status)
  local text = status;
  if text == nil or text == "" then
    text = "Waiting for AI orders";
  end
  if Controls == nil then
    return;
  end
  local button = Controls.EndTurnButton;
  if button ~= nil then
    if button.SetToolTipString ~= nil then
      pcall(function() button:SetToolTipString(text); end);
    end
    if button.SetText ~= nil then
      pcall(function() button:SetText(text); end);
    end
  end
  local label = Controls.EndTurnText or Controls.EndTurnLabel;
  if label ~= nil and label.SetText ~= nil then
    pcall(function() label:SetText(text); end);
  end
end

function OnEndTurnClicked()
  if _try_hold_end_turn() then
    local _, status = _waiting_status();
    _show_waiting_ui(status);
    return;
  end
  if BASE_OnEndTurnClicked ~= nil then
    BASE_OnEndTurnClicked();
    return;
  end
  if UI ~= nil and UI.RequestAction ~= nil and ActionTypes ~= nil then
    pcall(function() UI.RequestAction(ActionTypes.ACTION_ENDTURN); end);
  end
end

if BASE_DoEndTurn ~= nil then
  function DoEndTurn(...)
    if _try_hold_end_turn() then
      local _, status = _waiting_status();
      _show_waiting_ui(status);
      return;
    end
    return BASE_DoEndTurn(...);
  end
end
