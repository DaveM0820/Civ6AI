-- Civ6Ai: shared auto-close for the base game's engine-locking popups
-- (ExclusivePopupManager: natural disaster, natural wonder, wonder/project
-- built, era complete, corporation). Each locks the game-core event queue
-- (UI.ReferenceCurrentEvent) and bulk-hides the UI until its own Close()
-- runs; UIManager:DequeuePopup from another context only hides the screen,
-- so the turn froze (T28, catastrophic eruption). Under autotest the popup
-- context calls its own Close() after a short delay, exactly what Esc does:
-- the lock is released, the _Closed LuaEvent un-hides the UI and queued
-- popups chain. Local UI only, nothing synced, so multiplayer-safe.
-- Included by the per-popup ReplaceUIScript wrappers after the base file.

Civ6Ai_ExclusivePopup = Civ6Ai_ExclusivePopup or {}
Civ6Ai_ExclusivePopup.DELAY_SECONDS = 2.0

function Civ6Ai_ExclusivePopup.Enabled()
  local shared = ExposedMembers ~= nil and ExposedMembers.Civ6Ai or nil
  if shared == nil or shared.IsAutotest == nil then
    return false
  end
  local ok, on = pcall(shared.IsAutotest)
  return ok and on == true
end

function Civ6Ai_ExclusivePopup._Log(line)
  local shared = ExposedMembers ~= nil and ExposedMembers.Civ6Ai or nil
  if shared ~= nil and shared.Log ~= nil then
    pcall(shared.Log, line)
  else
    print("CIV6AI|" .. line)
  end
end

-- closeFn: the popup's own global Close (same path as Esc / the Close button).
function Civ6Ai_ExclusivePopup.Install(name, closeFn)
  if ContextPtr == nil or closeFn == nil then
    print("CIV6AI|exclusive_popup|install_skipped|name=" .. tostring(name))
    return
  end
  local shownFor = 0
  ContextPtr:SetUpdate(function(delta)
    if ContextPtr:IsHidden() or not Civ6Ai_ExclusivePopup.Enabled() then
      shownFor = 0
      return
    end
    shownFor = shownFor + (tonumber(delta) or 0)
    if shownFor < Civ6Ai_ExclusivePopup.DELAY_SECONDS then
      return
    end
    shownFor = 0
    local ok, err = pcall(closeFn)
    Civ6Ai_ExclusivePopup._Log("autotest|exclusive_popup_closed|name=" .. tostring(name)
      .. "|ok=" .. tostring(ok) .. (ok and "" or ("|err=" .. tostring(err))))
  end)
end
