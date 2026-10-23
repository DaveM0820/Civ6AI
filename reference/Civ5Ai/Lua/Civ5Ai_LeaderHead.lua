-- Loaded by LeaderHeadRoot as DiplomacyUIAddin. HostInbox/DiploCorner
-- SetUpdate does not run while this screen has focus, so Goodbye, leftover
-- skip, and inbox apply never ran. Pump those from here, and hand InGame
-- the queued LeaderHead context so DequeuePopup hits the same popup Goodbye uses.
print("CIV5AI|leaderhead|addin_loaded")

local function LeaderHeadRoot()
  if ContextPtr == nil or ContextPtr.LookUpControl == nil then
    return nil
  end
  return ContextPtr:LookUpControl("..")
end

-- FPS: LeaderHead SetUpdate is every frame while the diplo screen is up.
-- Trade dismiss / PumpTicks do not need 60Hz; 250ms is enough.
local CIV5AI_LEADERHEAD_MIN_INTERVAL = 0.25
local _civ5ai_leaderhead_last = 0

if ContextPtr ~= nil and ContextPtr.SetUpdate ~= nil then
  ContextPtr:SetUpdate(function()
    local root = LeaderHeadRoot()
    if root == nil or (root.IsHidden ~= nil and root:IsHidden()) then
      return
    end
    local now = (os and os.clock and os.clock()) or 0
    if (now - _civ5ai_leaderhead_last) < CIV5AI_LEADERHEAD_MIN_INTERVAL then
      return
    end
    _civ5ai_leaderhead_last = now
    local host = ExposedMembers ~= nil and ExposedMembers.Civ5Ai or nil
    if host == nil then
      return
    end
    host.LeaderHeadRoot = root
    if Civ5Ai_Diplo ~= nil and Civ5Ai_Diplo.HandleLeaderTradeBlocker ~= nil then
      local active = Game.GetActivePlayer()
      Civ5Ai_Diplo.HandleLeaderTradeBlocker(active)
      if Civ5Ai_Seats ~= nil
        and Civ5Ai_Seats.UsesFullLlmControl(active)
        and Civ5Ai_Diplo._TradeUiShowing ~= nil
        and Civ5Ai_Diplo._TradeUiShowing() then
        Civ5Ai_Diplo._PumpTradeUiDismiss(active)
      end
    end
    if host.PumpTicks ~= nil then
      host.PumpTicks()
    end
  end)
end
