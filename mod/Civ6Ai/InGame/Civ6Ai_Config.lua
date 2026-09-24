-- Civ6Ai seat manifest and runtime flags.
Civ6Ai_Config = Civ6Ai_Config or {}

function Civ6Ai_Config._Runtime()
  if Civ6Ai_Runtime ~= nil and Civ6Ai_Runtime.Root ~= nil and Civ6Ai_Runtime.Root ~= "" then
    return Civ6Ai_Runtime
  end
  if ExposedMembers ~= nil and ExposedMembers.Civ6Ai ~= nil then
    return ExposedMembers.Civ6Ai.Runtime
  end
  return nil
end

function Civ6Ai_Config.Initialize()
  local runtime = Civ6Ai_Config._Runtime()
  Civ6Ai_Config._managedSeats = Civ6Ai_Config._ParseSeatList(GameConfiguration.GetValue("CIV6AI_MANAGED_SEATS"))
  if Civ6Ai_Paths and Civ6Ai_Paths.ManagedSeats and Civ6Ai_Paths.ManagedSeats ~= "" then
    Civ6Ai_Config._managedSeats = Civ6Ai_Config._ParseSeatList(Civ6Ai_Paths.ManagedSeats)
  elseif runtime and runtime.ManagedSeats then
    Civ6Ai_Config._managedSeats = Civ6Ai_Config._ParseSeatList(runtime.ManagedSeats)
  end
  Civ6Ai_Config._humanSeats = Civ6Ai_Config._ParseSeatList(GameConfiguration.GetValue("CIV6AI_HUMAN_SEATS"))
  Civ6Ai_Config._autotest = GameConfiguration.GetValue("CIV6AI_AUTOTEST") == 1
  if Civ6Ai_Paths and tonumber(Civ6Ai_Paths.Autotest) == 1 then
    Civ6Ai_Config._autotest = true
  elseif runtime and tonumber(runtime.Autotest) == 1 then
    Civ6Ai_Config._autotest = true
  end
  Civ6Ai_Config._seatExperiment = GameConfiguration.GetValue("CIV6AI_SEAT_EXPERIMENT") == 1
  if Civ6Ai_Paths and Civ6Ai_Paths.SeatExperiment then
    Civ6Ai_Config._seatExperiment = Civ6Ai_Config._seatExperiment or tonumber(Civ6Ai_Paths.SeatExperiment) == 1
  end
  Civ6Ai_Config._enabled = GameConfiguration.GetValue("CIV6AI_ENABLED") ~= 0
  Civ6Ai_Config._fastEndTurn = GameConfiguration.GetValue("CIV6AI_FAST_END_TURN") == 1
  if Civ6Ai_Paths and tonumber(Civ6Ai_Paths.FastEndTurn) == 1 then
    Civ6Ai_Config._fastEndTurn = true
  elseif runtime and tonumber(runtime.FastEndTurn) == 1 then
    Civ6Ai_Config._fastEndTurn = true
  end
  if Civ6Ai_Paths and Civ6Ai_Paths.Civ6AiRoot and Civ6Ai_Paths.Civ6AiRoot ~= "" then
    Civ6Ai_Config._root = Civ6Ai_Paths.Civ6AiRoot
  elseif runtime and runtime.Root and runtime.Root ~= "" then
    Civ6Ai_Config._root = runtime.Root
  elseif Civ6Ai_Config._root ~= nil and Civ6Ai_Config._root ~= "" and Civ6Ai_Config._root ~= "civ6ai" then
    -- keep previously initialized root across UI reloads
  else
    Civ6Ai_Config._root = "civ6ai"
  end
  if runtime and runtime.SessionId and runtime.SessionId ~= "" then
    Civ6Ai_Config._sessionId = runtime.SessionId
  elseif Civ6Ai_Paths and Civ6Ai_Paths.SessionId and Civ6Ai_Paths.SessionId ~= "" then
    Civ6Ai_Config._sessionId = Civ6Ai_Paths.SessionId
  end
  Civ6Ai_Config._enableSinglePlayerChat = true
  if Civ6Ai_Paths and Civ6Ai_Paths.EnableSinglePlayerChat ~= nil then
    Civ6Ai_Config._enableSinglePlayerChat = tonumber(Civ6Ai_Paths.EnableSinglePlayerChat) == 1
  end
  Civ6Ai_Config._mpMoveSync = GameConfiguration.GetValue("CIV6AI_MP_MOVE_SYNC") == 1
  if Civ6Ai_Paths and tonumber(Civ6Ai_Paths.MpMoveSync) == 1 then
    Civ6Ai_Config._mpMoveSync = true
  elseif runtime and tonumber(runtime.MpMoveSync) == 1 then
    Civ6Ai_Config._mpMoveSync = true
  end
  local managed = {}
  for seat, enabled in pairs(Civ6Ai_Config._managedSeats) do
    if enabled then
      table.insert(managed, tostring(seat))
    end
  end
  table.sort(managed)
  Civ6Ai_Util.Log(
    "config|root=" .. tostring(Civ6Ai_Config._root)
      .. "|autotest=" .. tostring(Civ6Ai_Config._autotest)
      .. "|managed=" .. table.concat(managed, ",")
      .. "|sidecar_live=" .. tostring(Civ6Ai_Config.IsSidecarLive())
      .. "|fast_end_turn=" .. tostring(Civ6Ai_Config.IsFastEndTurn())
      .. "|sp_chat=" .. tostring(Civ6Ai_Config.EnableSinglePlayerChat())
      .. "|mp_move_sync=" .. tostring(Civ6Ai_Config.IsMpMoveSync())
      .. "|session=" .. tostring(Civ6Ai_Config.SessionId())
  )
end

function Civ6Ai_Config._ParseSeatList(raw)
  local seats = {}
  if raw == nil then
    return seats
  end
  local text = tostring(raw)
  for token in string.gmatch(text, "([^,]+)") do
    local seat = tonumber(token)
    if seat ~= nil then
      seats[seat] = true
    end
  end
  return seats
end

function Civ6Ai_Config.IsEnabled()
  return Civ6Ai_Config._enabled
end

function Civ6Ai_Config.IsAutotest()
  return Civ6Ai_Config._autotest
end

function Civ6Ai_Config.IsSeatExperiment()
  return Civ6Ai_Config._seatExperiment
end

function Civ6Ai_Config.IsHumanSeat(playerID)
  if Civ6Ai_Config._humanSeats[playerID] then
    return true
  end
  if Civ6Ai_Config.IsAutotest() and Civ6Ai_Config._managedSeats[playerID] then
    return false
  end
  local player = Players[playerID]
  if player ~= nil and player:IsHuman() and not Civ6Ai_Config.IsAutotest() then
    return true
  end
  return false
end

function Civ6Ai_Config.IsLlmControlledSeat(playerID)
  return Civ6Ai_Config.IsManagedSeat(playerID)
end

function Civ6Ai_Config.IsFastEndTurn()
  if Civ6Ai_Config.IsSidecarLive() then
    return false
  end
  return Civ6Ai_Config._fastEndTurn
end

function Civ6Ai_Config.EnableSinglePlayerChat()
  return Civ6Ai_Config._enableSinglePlayerChat == true
end

function Civ6Ai_Config.IsMpMoveSync()
  return Civ6Ai_Config._mpMoveSync == true
end

function Civ6Ai_Config.IsManagedSeat(playerID)
  if not Civ6Ai_Config.IsEnabled() then
    return false
  end
  if Civ6Ai_Config.IsHumanSeat(playerID) then
    return false
  end
  local player = Players[playerID]
  if player == nil or not player:IsAlive() or player:IsBarbarian() or player:IsFreeCities() then
    return false
  end
  if Civ6Ai_Config._managedSeats[playerID] then
    return true
  end
  if next(Civ6Ai_Config._managedSeats) == nil then
    return not player:IsHuman()
  end
  return false
end

function Civ6Ai_Config.ShouldRunBridge(playerID)
  if not Civ6Ai_Config.IsManagedSeat(playerID) then
    return false
  end
  if GameConfiguration.IsNetworkMultiplayer() then
    if Network ~= nil and Network.IsSessionHost ~= nil then
      return Network.IsSessionHost()
    end
    return false
  end
  return true
end

function Civ6Ai_Config.RootDir()
  return Civ6Ai_Config._root
end

function Civ6Ai_Config.SessionId()
  if Civ6Ai_Config._sessionId ~= nil and Civ6Ai_Config._sessionId ~= "" then
    return Civ6Ai_Config._sessionId
  end
  return ""
end

function Civ6Ai_Config.SidecarTimeout()
  local runtime = Civ6Ai_Config._Runtime()
  if Civ6Ai_Paths and Civ6Ai_Paths.SidecarTimeoutSeconds then
    return tonumber(Civ6Ai_Paths.SidecarTimeoutSeconds) or 45
  end
  if runtime and runtime.SidecarTimeoutSeconds then
    return tonumber(runtime.SidecarTimeoutSeconds) or 45
  end
  return 45
end

function Civ6Ai_Config.PythonExe()
  if Civ6Ai_Paths and Civ6Ai_Paths.Python and Civ6Ai_Paths.Python ~= "" then
    return Civ6Ai_Paths.Python
  end
  local runtime = Civ6Ai_Config._Runtime()
  if runtime and runtime.Python and runtime.Python ~= "" then
    return runtime.Python
  end
  return "python"
end

function Civ6Ai_Config.RepoRoot()
  if Civ6Ai_Paths and Civ6Ai_Paths.Repo and Civ6Ai_Paths.Repo ~= "" then
    return Civ6Ai_Paths.Repo
  end
  local runtime = Civ6Ai_Config._Runtime()
  if runtime and runtime.Repo and runtime.Repo ~= "" then
    return runtime.Repo
  end
  return ""
end

function Civ6Ai_Config.SidecarScript()
  if Civ6Ai_Paths and Civ6Ai_Paths.SidecarScript then
    return Civ6Ai_Paths.SidecarScript
  end
  return "sidecar/run_civ6.py"
end

function Civ6Ai_Config.IsSidecarLive()
  if Civ6Ai_Paths and tonumber(Civ6Ai_Paths.SidecarLive) == 1 then
    return true
  end
  local runtime = Civ6Ai_Config._Runtime()
  if runtime and tonumber(runtime.SidecarLive) == 1 then
    return true
  end
  return GameConfiguration.GetValue("CIV6AI_SIDECAR_LIVE") == 1
end

function Civ6Ai_Config.AutotestStopTurn()
  if Civ6Ai_Paths and Civ6Ai_Paths.AutotestStopTurn then
    return tonumber(Civ6Ai_Paths.AutotestStopTurn) or 20
  end
  return tonumber(GameConfiguration.GetValue("CIV6AI_AUTOTEST_STOP_TURN")) or 20
end

function Civ6Ai_Config.PersonalityPath(playerID)
  local repo = Civ6Ai_Config.RepoRoot()
  if repo == "" then
    return ""
  end
  return Civ6Ai_Util.JoinPath(repo, "fixtures/civ6/ai_player_" .. tostring(playerID) .. "_personality.json")
end

function Civ6Ai_Config.ManagedSeatsList()
  local seats = {}
  for seat, enabled in pairs(Civ6Ai_Config._managedSeats) do
    if enabled then
      table.insert(seats, seat)
    end
  end
  if #seats == 0 then
    for i = 0, 63 do
      local player = Players[i]
      if player ~= nil and player:IsAlive() and not player:IsBarbarian() and not player:IsFreeCities() then
        if Civ6Ai_Config.IsManagedSeat(i) then
          table.insert(seats, i)
        end
      end
    end
  end
  table.sort(seats)
  return seats
end
