-- Civ5Ai seat manifest and runtime flags (Paths-driven).
Civ5Ai_Config = Civ5Ai_Config or {}

function Civ5Ai_Config.Initialize()
  Civ5Ai_Config._managedSeats = Civ5Ai_Config._ParseSeatList("0,1,2,3")
  if Civ5Ai_Paths and Civ5Ai_Paths.ManagedSeats and Civ5Ai_Paths.ManagedSeats ~= "" then
    Civ5Ai_Config._managedSeats = Civ5Ai_Config._ParseSeatList(Civ5Ai_Paths.ManagedSeats)
  end
  Civ5Ai_Config._autotest = false
  if Civ5Ai_Paths and tonumber(Civ5Ai_Paths.Autotest) == 1 then
    Civ5Ai_Config._autotest = true
  end
  Civ5Ai_Config._coActive = false
  if Civ5Ai_Paths and tonumber(Civ5Ai_Paths.CoActive) == 1 then
    Civ5Ai_Config._coActive = true
  end
  Civ5Ai_Config._parallelPulses = false
  if Civ5Ai_Paths and tonumber(Civ5Ai_Paths.ParallelPulses) == 1 then
    Civ5Ai_Config._parallelPulses = true
    if not Civ5Ai_Config._coActive then
      Civ5Ai_Config._parallelPulses = false
      Civ5Ai_Util.Log("config|parallel_pulses_ignored|requires_co_active=1")
    end
  end
  Civ5Ai_Config._netApply = true
  if Civ5Ai_Paths and Civ5Ai_Paths.NetApply ~= nil and tonumber(Civ5Ai_Paths.NetApply) == 0 then
    Civ5Ai_Config._netApply = false
  end
  Civ5Ai_Config._enabled = true
  Civ5Ai_Config._fastEndTurn = false
  if Civ5Ai_Paths and tonumber(Civ5Ai_Paths.FastEndTurn) == 1 then
    Civ5Ai_Config._fastEndTurn = true
  end
  Civ5Ai_Config._responsiveWait = false
  if Civ5Ai_Paths and tonumber(Civ5Ai_Paths.ResponsiveWait) == 1 then
    Civ5Ai_Config._responsiveWait = true
  end
  if Civ5Ai_Paths and Civ5Ai_Paths.Civ5AiRoot and Civ5Ai_Paths.Civ5AiRoot ~= "" then
    Civ5Ai_Config._root = Civ5Ai_Paths.Civ5AiRoot
  else
    Civ5Ai_Config._root = "civ5ai"
  end
  if Civ5Ai_Paths and Civ5Ai_Paths.SessionId and Civ5Ai_Paths.SessionId ~= "" then
    Civ5Ai_Config._sessionId = Civ5Ai_Paths.SessionId
  end
  if Civ5Ai_Seats ~= nil and Civ5Ai_Seats.Initialize ~= nil then
    Civ5Ai_Seats.Initialize()
  end
  Civ5Ai_Config._SyncManagedSeatsToDll()
  local managed = {}
  for seat, enabled in pairs(Civ5Ai_Config._managedSeats) do
    if enabled then
      table.insert(managed, tostring(seat))
    end
  end
  table.sort(managed)
  Civ5Ai_Util.Log(
    "config|root=" .. tostring(Civ5Ai_Config._root)
      .. "|autotest=" .. tostring(Civ5Ai_Config._autotest)
      .. "|co_active=" .. tostring(Civ5Ai_Config._coActive)
      .. "|parallel_pulses=" .. tostring(Civ5Ai_Config._parallelPulses)
      .. "|net_apply=" .. tostring(Civ5Ai_Config._netApply)
      .. "|managed=" .. table.concat(managed, ",")
      .. "|sidecar_live=" .. tostring(Civ5Ai_Config.IsSidecarLive())
      .. "|fast_end_turn=" .. tostring(Civ5Ai_Config.IsFastEndTurn())
      .. "|responsive_wait=" .. tostring(Civ5Ai_Config.IsResponsiveWait())
      .. "|session=" .. tostring(Civ5Ai_Config.SessionId())
  )
end

function Civ5Ai_Config._SyncManagedSeatsToDll()
  if Game == nil or Game.SetCiv5AiManagedSeats == nil then
    return
  end
  local seats = {}
  for seat = 0, 63 do
    if Civ5Ai_Config.IsManagedSeat(seat) then
      table.insert(seats, seat)
    end
  end
  Game.SetCiv5AiManagedSeats(seats)
  if Game.SetCiv5AiCoActiveMode ~= nil then
    Game.SetCiv5AiCoActiveMode(Civ5Ai_Config._coActive and 1 or 0)
  end
  Civ5Ai_Util.Log(
    "config|dll_managed_seats|"
      .. table.concat(seats, ",")
      .. "|co_active="
      .. tostring(Civ5Ai_Config._coActive)
  )
end

function Civ5Ai_Config._ParseSeatList(raw)
  local seats = {}
  if raw == nil then
    return seats
  end
  for token in string.gmatch(tostring(raw), "([^,]+)") do
    local seat = tonumber(token)
    if seat ~= nil then
      seats[seat] = true
    end
  end
  return seats
end

function Civ5Ai_Config.IsEnabled()
  return Civ5Ai_Config._enabled
end

function Civ5Ai_Config.IsAutotest()
  return Civ5Ai_Config._autotest
end

function Civ5Ai_Config.IsCoActiveMode()
  return Civ5Ai_Config._coActive == true
end

function Civ5Ai_Config.IsParallelPulses()
  return Civ5Ai_Config._parallelPulses == true
end

function Civ5Ai_Config.IsNetApply()
  return Civ5Ai_Config._netApply == true
end

function Civ5Ai_Config.IsHumanSeat(playerID)
  return Civ5Ai_Seats ~= nil and Civ5Ai_Seats.IsLocalHuman(playerID)
end

function Civ5Ai_Config.IsFastEndTurn()
  if Civ5Ai_Config.IsSidecarLive() then
    return false
  end
  return Civ5Ai_Config._fastEndTurn
end

function Civ5Ai_Config.IsResponsiveWait()
  if not Civ5Ai_Config.IsSidecarLive() then
    return false
  end
  return Civ5Ai_Config._responsiveWait == true
end

function Civ5Ai_Config.IsManagedSeat(playerID)
  if Civ5Ai_Seats ~= nil and Civ5Ai_Seats.ShouldPulse ~= nil then
    return Civ5Ai_Seats.ShouldPulse(playerID)
  end
  return false
end

function Civ5Ai_Config.IsNetworkMultiplayer()
  return Game ~= nil
    and Game.IsNetworkMultiPlayer ~= nil
    and Game.IsNetworkMultiPlayer() == true
end

function Civ5Ai_Config.IsSessionHost()
  if not Civ5Ai_Config.IsNetworkMultiplayer() then
    return true
  end
  return Network ~= nil and Network.IsSessionHost ~= nil and Network.IsSessionHost() == true
end

function Civ5Ai_Config.ShouldRunBridge(playerID)
  if not Civ5Ai_Config.IsManagedSeat(playerID) then
    return false
  end
  if Civ5Ai_Config.IsNetworkMultiplayer() then
    return Civ5Ai_Config.IsSessionHost()
  end
  return true
end

function Civ5Ai_Config.RootDir()
  return Civ5Ai_Config._root
end

function Civ5Ai_Config.SessionId()
  if Civ5Ai_Config._sessionId ~= nil and Civ5Ai_Config._sessionId ~= "" then
    return Civ5Ai_Config._sessionId
  end
  return ""
end

function Civ5Ai_Config.SidecarTimeout()
  if Civ5Ai_Paths and Civ5Ai_Paths.SidecarTimeoutSeconds then
    return tonumber(Civ5Ai_Paths.SidecarTimeoutSeconds) or 120
  end
  return 120
end

function Civ5Ai_Config.SeatTurnCapSeconds()
  if Civ5Ai_Paths and Civ5Ai_Paths.SeatTurnCapSeconds then
    local cap = tonumber(Civ5Ai_Paths.SeatTurnCapSeconds)
    if cap ~= nil and cap > 0 then
      return cap
    end
  end
  return Civ5Ai_Config.SidecarTimeout()
end

function Civ5Ai_Config.PythonExe()
  if Civ5Ai_Paths and Civ5Ai_Paths.Python and Civ5Ai_Paths.Python ~= "" then
    return Civ5Ai_Paths.Python
  end
  return "python"
end

function Civ5Ai_Config.RepoRoot()
  if Civ5Ai_Paths and Civ5Ai_Paths.Repo and Civ5Ai_Paths.Repo ~= "" then
    return Civ5Ai_Paths.Repo
  end
  return ""
end

function Civ5Ai_Config.SidecarScript()
  if Civ5Ai_Paths and Civ5Ai_Paths.SidecarScript then
    return Civ5Ai_Paths.SidecarScript
  end
  return "sidecar/run_civ5.py"
end

function Civ5Ai_Config.IsSidecarLive()
  if Civ5Ai_Paths and tonumber(Civ5Ai_Paths.SidecarLive) == 1 then
    return true
  end
  return false
end

function Civ5Ai_Config.AutotestStopTurn()
  if Civ5Ai_Paths and Civ5Ai_Paths.AutotestStopTurn then
    return tonumber(Civ5Ai_Paths.AutotestStopTurn) or 20
  end
  return 20
end

function Civ5Ai_Config.PersonalityPath(playerID)
  local repo = Civ5Ai_Config.RepoRoot()
  if repo == "" then
    return ""
  end
  return Civ5Ai_Util.JoinPath(repo, "fixtures/civ5/ai_player_" .. tostring(playerID) .. "_personality.json")
end

function Civ5Ai_Config.ManagedSeatsList()
  local seats = {}
  for seat, enabled in pairs(Civ5Ai_Config._managedSeats) do
    if enabled then
      table.insert(seats, seat)
    end
  end
  table.sort(seats)
  return seats
end
