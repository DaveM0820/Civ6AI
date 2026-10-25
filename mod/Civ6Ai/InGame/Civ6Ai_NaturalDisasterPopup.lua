-- Civ6Ai: NaturalDisasterPopup with autotest auto-close (see Civ6Ai_ExclusivePopup.lua).
-- Loads the most specific base/DLC script; ours only adds the close timer.
if Close == nil then pcall(function() include("NaturalDisasterPopup_GranColombia_Maya"); end); end
if Close == nil then pcall(function() include("NaturalDisasterPopup"); end); end
include("Civ6Ai_ExclusivePopup");
Civ6Ai_ExclusivePopup.Install("NaturalDisasterPopup", Close);
