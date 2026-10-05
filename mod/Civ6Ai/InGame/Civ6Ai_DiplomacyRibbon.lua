-- Civ6Ai: include alive major AI seats on the vanilla DiplomacyRibbon.
-- Firaxis only adds unmet majors when they are multiplayer humans
-- (DiplomacyRibbon.UpdateLeaders: isMet or isHumanMP). Managed AI seats
-- therefore never appear top-right, so turn-complete slide animations never
-- run for them. After the base/expansion UpdateLeaders, add any missing
-- alive majors via the stock AddLeader path — no custom reorder.

if not pcall(function() include("DiplomacyRibbon_Expansion2"); end) then
  if not pcall(function() include("DiplomacyRibbon_Expansion1"); end) then
    include("DiplomacyRibbon");
  end
end

BASE_Civ6Ai_UpdateLeaders = UpdateLeaders;

-- ===========================================================================
function UpdateLeaders()
  BASE_Civ6Ai_UpdateLeaders();

  local localPlayerID:number = Game.GetLocalPlayer();
  if localPlayerID == nil or localPlayerID == PlayerTypes.NONE or localPlayerID == PlayerTypes.OBSERVER then
    return;
  end

  local byId:table = GetUILeadersByID();
  if byId == nil then
    return;
  end

  local localDip = nil;
  if Players[localPlayerID] ~= nil then
    localDip = Players[localPlayerID]:GetDiplomacy();
  end

  local added:boolean = false;
  for _, pPlayer in ipairs(PlayerManager.GetAliveMajors()) do
    local playerID:number = pPlayer:GetID();
    if playerID ~= localPlayerID and byId[playerID] == nil then
      local pPlayerConfig:table = PlayerConfigurations[playerID];
      if pPlayerConfig ~= nil then
        local leaderName:string = pPlayerConfig:GetLeaderTypeName();
        local isMet:boolean = false;
        if localDip ~= nil and localDip.HasMet ~= nil then
          local ok, met = pcall(function() return localDip:HasMet(playerID); end);
          if ok and met then
            isMet = true;
          end
        end
        -- Same masking rule as unmet MP humans: show portrait, hide yields until met.
        local iconName:string = "ICON_LEADER_DEFAULT";
        if leaderName ~= nil then
          iconName = "ICON_" .. leaderName;
        end
        AddLeader(iconName, playerID, {
          isMasked = (not isMet),
          isUnique = true
        });
        added = true;
      end
    end
  end

  if added and RealizeSize ~= nil then
    RealizeSize();
  end
end
