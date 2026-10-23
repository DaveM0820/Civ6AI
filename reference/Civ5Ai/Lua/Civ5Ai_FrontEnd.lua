-- FrontEnd helper: enable Community Patch, then walk the Mods screens
-- (EULA ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Browser Next ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Single Player ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Play Map ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Start).
-- Next on the Mods Browser is what calls Modding.ActivateEnabledMods(),
-- which loads the patched game DLL. That DLL is how a command string is
-- sent once and received on every computer. Do not start a vanilla game.
print("CIV5AI|frontend|file_loaded")
local CP_ID = "d1b6328c-ff44-4b0d-aad7-c657f83610cd"

pcall(function()
  include("Civ5Ai_autostart")
end)

local function ShouldAutostart()
  if Civ5Ai_Autostart == true then
    return true
  end
  if os ~= nil and os.getenv ~= nil and os.getenv("CIV5AI_AUTOSTART") == "1" then
    return true
  end
  return false
end

-- Wait in this screen's update after ShowHide has returned, so
-- ActivateEnabledMods is not nested inside another screen's popup.
local function AfterSeconds(seconds, fn)
  if ContextPtr == nil or ContextPtr.SetUpdate == nil then
    fn()
    return
  end
  local elapsed = 0
  ContextPtr:SetUpdate(function(dt)
    elapsed = elapsed + (dt or 0.016)
    if elapsed < seconds then
      return
    end
    ContextPtr:ClearUpdate()
    fn()
  end)
end

local function LookupCommunityPatchVersion()
  if Modding == nil or Modding.GetModBrowserInstalledListings == nil then
    return 151
  end
  local listings = Modding.GetModBrowserInstalledListings()
  if listings == nil then
    return 151
  end
  for _, mod in pairs(listings) do
    local id = mod.ModId or mod.ModID
    if id == CP_ID then
      return mod.Version or 151
    end
  end
  return 151
end

local function EnableCommunityPatch()
  if Modding == nil then
    print("CIV5AI|frontend|modding_unavailable")
    return false
  end
  -- Only Community Patch. Other enabled mods make Next rebuild extra SQL
  -- and are not needed: Civ5Ai Lua is already in InGame via the DLC hooks.
  if Modding.GetModBrowserInstalledListings ~= nil then
    local listings = Modding.GetModBrowserInstalledListings()
    if listings ~= nil then
      for _, mod in pairs(listings) do
        local id = mod.ModId or mod.ModID
        if id ~= nil and id ~= CP_ID then
          local version = mod.Version
          print("CIV5AI|frontend|disable_mod|" .. tostring(id) .. "|v=" .. tostring(version))
          pcall(function()
            Modding.DisableMod(id, version)
          end)
        end
      end
    end
  end
  local version = LookupCommunityPatchVersion()
  print("CIV5AI|frontend|enable_begin|version=" .. tostring(version))
  local ok, err = pcall(function()
    Modding.EnableMod(CP_ID, version)
  end)
  print("CIV5AI|frontend|enable_mod|ok=" .. tostring(ok) .. "|" .. tostring(err))
  return ok
end

function Civ5Ai_FrontEndTryStart()
  print("CIV5AI|frontend|try_start")
end

local contextId = "?"
if ContextPtr ~= nil and ContextPtr.GetID ~= nil then
  contextId = tostring(ContextPtr:GetID())
end
print("CIV5AI|frontend|context=" .. contextId)

if not ShouldAutostart() then
  return
end

-- First FrontEnd popup: legal / ESRB "CLICK TO CONTINUE".
if contextId == "LegalScreen" or (Controls ~= nil and Controls.ContinueButton ~= nil and Controls.ActivateButton == nil) then
  ContextPtr:SetShowHideHandler(function(isHide)
    if isHide or Civ5Ai_FrontEndLegalDone then
      return
    end
    Civ5Ai_FrontEndLegalDone = true
    AfterSeconds(0.5, function()
      print("CIV5AI|frontend|legal_continue")
      UIManager:DequeuePopup(ContextPtr)
    end)
  end)

elseif Controls ~= nil and Controls.ActivateButton ~= nil and OnActivateButtonClicked ~= nil then
  -- Dawn of Man / load screen: "Begin your journey" (ActivateButton).
  -- Stock SequenceGameInitComplete unhides that button first; click only then.
  Events.SequenceGameInitComplete.Add(function()
    local tries = 0
    local function TryActivate()
      tries = tries + 1
      local hidden = true
      if Controls.ActivateButton.IsHidden ~= nil then
        hidden = Controls.ActivateButton:IsHidden()
      else
        hidden = false
      end
      if not hidden or tries >= 40 then
        print("CIV5AI|frontend|loadscreen_activate")
        OnActivateButtonClicked()
        return
      end
      AfterSeconds(0.25, TryActivate)
    end
    AfterSeconds(0.25, TryActivate)
  end)

elseif contextId == "MainMenu" then
  local previous = ShowHideHandler
  function ShowHideHandler(bIsHide, bIsInit)
    if previous ~= nil then
      previous(bIsHide, bIsInit)
    end
    if bIsHide or Civ5Ai_FrontEndOpenedMods then
      return
    end
    Civ5Ai_FrontEndOpenedMods = true
    print("CIV5AI|frontend|kick_mainmenu")
    AfterSeconds(2, function()
      if not EnableCommunityPatch() then
        return
      end
      print("CIV5AI|frontend|open_eula")
      ModsButtonClick()
    end)
  end
  ContextPtr:SetShowHideHandler(ShowHideHandler)

elseif contextId == "ModsEULAScreen" then
  ContextPtr:SetShowHideHandler(function(isHide)
    if isHide or Civ5Ai_FrontEndEulaDone then
      return
    end
    Civ5Ai_FrontEndEulaDone = true
    AfterSeconds(1, function()
      print("CIV5AI|frontend|eula_accept")
      OnAccept()
    end)
  end)

elseif contextId == "ModsBrowser" then
  -- Next = OnNextButtonClicked (same as LargeButton). Prefer SystemUpdateUI /
  -- Enter InputHandler so ActivateEnabledMods is not nested in SetUpdate/ShowHide.
  local function DoModsNext(reason)
    if Civ5Ai_FrontEndBrowserNext or OnNextButtonClicked == nil then
      return
    end
    Civ5Ai_FrontEndBrowserNext = true
    print("CIV5AI|frontend|mods_next_begin|" .. tostring(reason or "auto"))
    OnNextButtonClicked()
    print("CIV5AI|frontend|mods_next_done|" .. tostring(reason or "auto"))
  end

  local previousInput = InputHandler
  function InputHandler(uiMsg, wParam, lParam)
    if not Civ5Ai_FrontEndBrowserNext
      and uiMsg == KeyEvents.KeyDown
      and wParam == Keys.VK_RETURN then
      DoModsNext("enter")
      return true
    end
    if previousInput ~= nil then
      return previousInput(uiMsg, wParam, lParam)
    end
    return true
  end
  ContextPtr:SetInputHandler(InputHandler)

  ContextPtr:SetShowHideHandler(function(bHiding)
    if bHiding then
      return
    end
    if Controls ~= nil and Controls.SmallButton2 ~= nil and Steam ~= nil then
      Controls.SmallButton2:SetHide(not Steam.IsOverlayEnabled())
    end
    if Civ5Ai_FrontEndBrowserReady then
      return
    end
    Civ5Ai_FrontEndBrowserReady = true
    print("CIV5AI|frontend|mods_browser_ready")
    -- Arm Next on next SystemUpdateUI (works with -Automation path).
    if Events ~= nil and Events.SystemUpdateUI ~= nil and not Civ5Ai_FrontEndBrowserNextArmed then
      Civ5Ai_FrontEndBrowserNextArmed = true
      print("CIV5AI|frontend|mods_next_armed_systemupdate")
      local fired = false
      Events.SystemUpdateUI.Add(function()
        if fired or Civ5Ai_FrontEndBrowserNext then
          return
        end
        fired = true
        DoModsNext("systemupdate")
      end)
    end
  end)

elseif contextId == "ModsMenu" then
  ContextPtr:SetShowHideHandler(function(isHiding)
    if isHiding or Civ5Ai_FrontEndModsMenuDone then
      return
    end
    Civ5Ai_FrontEndModsMenuDone = true
    AfterSeconds(1, function()
      print("CIV5AI|frontend|modsmenu_sp")
      OnSinglePlayerClick()
    end)
  end)

elseif contextId == "ModdingSinglePlayer" then
  ContextPtr:SetShowHideHandler(function(isHiding)
    if isHiding or Civ5Ai_FrontEndPlayMapDone then
      return
    end
    Civ5Ai_FrontEndPlayMapDone = true
    AfterSeconds(1, function()
      -- Resolve LoadSave robustly: include, absolute dofile, getenv, load_save_path.txt.
      -- NEVER fall through to play_map when a continue save is configured.
      pcall(function()
        include("Civ5Ai_Util")
      end)
      pcall(function()
        include("Civ5Ai_Paths")
      end)
      -- no_io_v2: FrontEnd has no io/dofile. Use Civ5Ai_Util / Game.ReadTextFile only.
      local function ReadTextFileSafe(path)
        if path == nil or path == "" then
          return nil
        end
        local body = nil
        if Civ5Ai_Util ~= nil and Civ5Ai_Util.ReadTextFile ~= nil then
          local ok, text = pcall(Civ5Ai_Util.ReadTextFile, path)
          if ok and text ~= nil and text ~= "" then
            body = text
          end
        end
        if (body == nil or body == "") and Game ~= nil and Game.ReadTextFile ~= nil then
          local ok2, text2 = pcall(Game.ReadTextFile, path)
          if ok2 and text2 ~= nil and text2 ~= "" then
            body = text2
          end
        end
        if body == nil or body == "" then
          return nil
        end
        body = string.gsub(body, "^\239\187\191", "")
        body = string.gsub(body, "^%s+", "")
        body = string.gsub(body, "%s+$", "")
        if body == "" then
          return nil
        end
        return body
      end
      local loadSave = nil
      print("CIV5AI|frontend|paths_state|nil=" .. tostring(Civ5Ai_Paths == nil))
      if Civ5Ai_Paths ~= nil then
        print("CIV5AI|frontend|paths_session|" .. tostring(Civ5Ai_Paths.SessionId))
        print("CIV5AI|frontend|paths_loadsave|" .. tostring(Civ5Ai_Paths.LoadSaveFile))
      end
      if Civ5Ai_Paths ~= nil and Civ5Ai_Paths.LoadSaveFile ~= nil and Civ5Ai_Paths.LoadSaveFile ~= "" then
        loadSave = tostring(Civ5Ai_Paths.LoadSaveFile)
        print("CIV5AI|frontend|load_save_from|paths_lua")
      end
      if (loadSave == nil or loadSave == "") and os ~= nil and os.getenv ~= nil then
        local envSave = os.getenv("CIV5AI_LOAD_SAVE")
        if envSave ~= nil and envSave ~= "" then
          loadSave = envSave
          print("CIV5AI|frontend|load_save_from|env")
        end
      end
      if loadSave == nil or loadSave == "" then
        local stamp = ReadTextFileSafe("C:/Users/dmitc/OneDrive/Documents/My Games/Sid Meier's Civilization 5/MODS/Civ5Ai/runtime/load_save_path.txt")
        if stamp ~= nil then
          loadSave = stamp
          print("CIV5AI|frontend|load_save_from|stamp_file")
        end
      end
      if loadSave ~= nil and loadSave ~= "" then
        print("CIV5AI|frontend|load_save|" .. loadSave)
        local ok1, err1 = pcall(function()
          if PreGame ~= nil and PreGame.SetLoadFileName ~= nil then
            PreGame.SetLoadFileName(loadSave)
          end
        end)
        print("CIV5AI|frontend|set_load_file|ok=" .. tostring(ok1) .. "|" .. tostring(err1))
        local ok2, err2 = pcall(function()
          if Events ~= nil and Events.PlayerChoseToLoadGame ~= nil then
            Events.PlayerChoseToLoadGame(loadSave)
          end
        end)
        print("CIV5AI|frontend|player_chose_load|ok=" .. tostring(ok2) .. "|" .. tostring(err2))
        return
      end
      print("CIV5AI|frontend|play_map")
      UIManager:QueuePopup(Controls.ModdingGameSetupScreen, PopupPriority.ModdingGameSetupScreen)
    end)
  end)

elseif contextId == "ModdingGameSetupScreen" then
  pcall(function()
    include("Civ5Ai_Paths")
  end)

  local function ProfileValue(name, default)
    if Civ5Ai_Paths ~= nil and Civ5Ai_Paths[name] ~= nil and Civ5Ai_Paths[name] ~= "" then
      return Civ5Ai_Paths[name]
    end
    if name == "MajorCount" and Civ5Ai_MajorCount ~= nil then
      return Civ5Ai_MajorCount
    end
    if (name == "MapScript" or name == "Civ5Ai_MapScript") and Civ5Ai_MapScript ~= nil then
      return Civ5Ai_MapScript
    end
    if name == "WorldSize" and Civ5Ai_WorldSize ~= nil then
      return Civ5Ai_WorldSize
    end
    if name == "GameSpeed" and Civ5Ai_GameSpeed ~= nil then
      return Civ5Ai_GameSpeed
    end
    if name == "MapType" and Civ5Ai_MapType ~= nil then
      return Civ5Ai_MapType
    end
    if name == "Handicap" and Civ5Ai_Handicap ~= nil then
      return Civ5Ai_Handicap
    end
    return default
  end

  local function ProfileNumber(name, default)
    return tonumber(ProfileValue(name, default)) or default
  end

  local function ProfileString(name, default)
    local value = ProfileValue(name, default)
    if value == nil then
      return default
    end
    return tostring(value)
  end

  local function ResolveGameSpeed()
    local preferred = ProfileString("GameSpeed", "")
    local candidates = {}
    if preferred ~= nil and preferred ~= "" then
      table.insert(candidates, preferred)
    end
    for _, speedType in ipairs({ "GAMESPEED_TURBO", "GAMESPEED_FAST", "GAMESPEED_QUICK" }) do
      table.insert(candidates, speedType)
    end
    if GameInfo == nil or GameInfo.GameSpeeds == nil then
      return nil, preferred
    end
    if preferred ~= nil and preferred ~= "" and GameInfo.GameSpeeds[preferred] == nil then
      print("CIV5AI|frontend|gamespeed_missing|" .. tostring(preferred))
    end
    for _, speedType in ipairs(candidates) do
      local row = GameInfo.GameSpeeds[speedType]
      if row ~= nil then
        return row, speedType
      end
    end
    return nil, preferred
  end

  local function ResolveMapScript(worldType)
    local mapType = ProfileString("MapType", "MAP_TERRA")
    if mapType ~= nil and mapType ~= "" and GameInfo ~= nil and GameInfo.Maps ~= nil then
      local mapEntry = GameInfo.Maps[mapType]
      if mapEntry ~= nil and GameInfo.Map_Sizes ~= nil then
        for row in GameInfo.Map_Sizes{ MapType = mapType, WorldSizeType = worldType } do
          if row.FileName ~= nil and row.FileName ~= "" then
            return row.FileName
          end
        end
        for row in GameInfo.Map_Sizes{ MapType = mapType } do
          if row.WorldSizeType == worldType and row.FileName ~= nil and row.FileName ~= "" then
            return row.FileName
          end
        end
      end
    end
    local mapScript = ProfileString("Civ5Ai_MapScript", nil)
    if mapScript == nil or mapScript == "" then
      mapScript = ProfileString("MapScript", "Assets\\Maps\\Terra.lua")
    end
    return mapScript
  end

  local function ResolveHandicap()
    local handicapType = ProfileString("Handicap", "HANDICAP_PRINCE")
    if handicapType == nil or handicapType == "" then
      handicapType = "HANDICAP_PRINCE"
    end
    if GameInfo == nil or GameInfo.HandicapInfos == nil then
      return nil, handicapType
    end
    local row = GameInfo.HandicapInfos[handicapType]
    if row == nil then
      row = GameInfo.HandicapInfos["HANDICAP_PRINCE"]
      handicapType = "HANDICAP_PRINCE"
    end
    return row, handicapType
  end

  local function ConfigureHandicap(majorCount)
    if PreGame == nil or PreGame.SetHandicap == nil or majorCount == nil then
      return nil
    end
    local handicap, handicapType = ResolveHandicap()
    if handicap == nil then
      return nil
    end
    for i = 0, majorCount - 1 do
      PreGame.SetHandicap(i, handicap.ID)
    end
    return handicapType
  end

  local function UsesFairHandicap()
    if Civ5Ai_Seats ~= nil and Civ5Ai_Seats.UsesFairHandicap ~= nil then
      return Civ5Ai_Seats.UsesFairHandicap()
    end
    return ProfileString("ComputerMode", "llm_human") == "llm_human"
  end

  local function ConfigureLaunchProfile()
    if PreGame == nil then
      print("CIV5AI|frontend|pregame_unavailable")
      return
    end
    if PreGame.SetRandomWorldSize ~= nil then
      PreGame.SetRandomWorldSize(false)
    end
    if PreGame.SetRandomMapScript ~= nil then
      PreGame.SetRandomMapScript(false)
    end
    if PreGame.SetLoadWBScenario ~= nil then
      PreGame.SetLoadWBScenario(false)
    end

    local worldType = ProfileString("WorldSize", "WORLDSIZE_DUEL")
    local world = nil
    if GameInfo ~= nil and GameInfo.Worlds ~= nil then
      world = GameInfo.Worlds[worldType]
      if world == nil then
        world = GameInfo.Worlds["WORLDSIZE_DUEL"]
        worldType = "WORLDSIZE_DUEL"
      end
    end
    if world ~= nil and PreGame.SetWorldSize ~= nil then
      PreGame.SetWorldSize(world.ID)
      if PreGame.SetNumMinorCivs ~= nil and world.DefaultMinorCivs ~= nil then
        PreGame.SetNumMinorCivs(world.DefaultMinorCivs)
      end
    end

    local mapScript = ResolveMapScript(worldType)
    if PreGame.SetMapScript ~= nil and mapScript ~= nil and mapScript ~= "" then
      PreGame.SetMapScript(mapScript)
    end

    local speed, speedType = ResolveGameSpeed()
    if speed ~= nil and PreGame.SetGameSpeed ~= nil then
      PreGame.SetGameSpeed(speed.ID)
    end

    local majorCount = ProfileNumber("Civ5Ai_MajorCount", nil)
    if majorCount == nil then
      majorCount = ProfileNumber("MajorCount", 4)
    end
    local handicapType = ConfigureHandicap(majorCount)

    print(
      "CIV5AI|frontend|setup|world="
        .. tostring(worldType)
        .. "|speed="
        .. tostring(speedType)
        .. "|map="
        .. tostring(mapScript)
        .. "|handicap="
        .. tostring(handicapType or "unknown")
        .. "|fair_handicap="
        .. tostring(UsesFairHandicap())
    )
  end
  local function ConfigureAllAiSeats()
    if PreGame == nil or SlotStatus == nil then
      print("CIV5AI|frontend|slots_unavailable")
      return
    end
    local majorCount = ProfileNumber("Civ5Ai_MajorCount", nil)
    if majorCount == nil then
      majorCount = ProfileNumber("MajorCount", 4)
    end
    if majorCount < 1 then
      majorCount = 1
    end
    local fairHandicap = UsesFairHandicap()
    -- Fair LLM mode: all managed majors are human slots so everyone gets the
    -- player handicap column (no AI-only production/research cheats). Seat 0
    -- remains the only local client; FinishSeat uses IsActiveLocalPlayer.
    for i = 0, majorCount - 1 do
      if fairHandicap or i == 0 then
        PreGame.SetSlotStatus(i, SlotStatus.SS_TAKEN)
      else
        PreGame.SetSlotStatus(i, SlotStatus.SS_COMPUTER)
      end
      if i == 0 then
        local poly = nil
        if GameInfo ~= nil and GameInfo.Civilizations ~= nil then
          poly = GameInfo.Civilizations["CIVILIZATION_POLYNESIA"]
        end
        if poly ~= nil and poly.ID ~= nil then
          PreGame.SetCivilization(i, poly.ID)
        else
          PreGame.SetCivilization(i, -1)
        end
      else
        PreGame.SetCivilization(i, -1)
      end
    end
    local lastMajor = 21
    if GameDefines ~= nil and GameDefines.MAX_MAJOR_CIVS ~= nil then
      lastMajor = GameDefines.MAX_MAJOR_CIVS - 1
    end
    for i = majorCount, lastMajor do
      PreGame.SetSlotStatus(i, SlotStatus.SS_CLOSED)
    end
    print(
      "CIV5AI|frontend|slots|majors="
        .. tostring(majorCount)
        .. "|fair_handicap="
        .. tostring(fairHandicap)
        .. "|taken=0"
        .. (fairHandicap and ("-" .. tostring(majorCount - 1)) or "|computer=1-" .. tostring(majorCount - 1))
    )
  end
  local previousSetup = ShowHideHandler
  function ShowHideHandler(isHide, isInit)
    if isHide then
      if previousSetup ~= nil then
        previousSetup(isHide, isInit)
      end
      return
    end
    if Civ5Ai_FrontEndStarted then
      if previousSetup ~= nil then
        previousSetup(isHide, isInit)
      end
      return
    end
    Civ5Ai_FrontEndStarted = true
    ConfigureLaunchProfile()
    ConfigureAllAiSeats()
    if previousSetup ~= nil then
      previousSetup(isHide, isInit)
    end
    AfterSeconds(1, function()
      print("CIV5AI|frontend|setup_start")
      OnStart()
    end)
  end
  ContextPtr:SetShowHideHandler(ShowHideHandler)
end

