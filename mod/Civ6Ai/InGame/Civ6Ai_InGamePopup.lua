-- Civ6Ai: InGamePopup with autotest auto-close (see Civ6Ai_ExclusivePopup.lua).
-- InGamePopup hosts every PopupDialogInGame (Unit Captured, generic OK /
-- confirm dialogs raised via LuaEvents.OnRaisePopupInGame). It is a modal
-- (UIManager:PushModal) that eats all input until dismissed. Under autotest we
-- close it through its own OnClosePopup (PopModal + dialog Close, same as Esc
-- falling through) after a short delay, logging the raising popup's id.
-- No button callback runs, i.e. the dialog is dismissed, never confirmed.
include("InGamePopup");
include("Civ6Ai_ExclusivePopup");
local m_lastId = "InGamePopup";
LuaEvents.OnRaisePopupInGame.Add(function(id) m_lastId = "InGamePopup:" .. tostring(id); end);
Civ6Ai_ExclusivePopup.Install(function() return m_lastId; end, OnClosePopup);
