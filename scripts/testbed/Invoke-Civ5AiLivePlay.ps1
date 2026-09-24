# Live Civ5Ai: sidecar LLM on managed seats.
# Unattended (-Autoplay): human seat 0 on the LLM, Community Patch on the rest.
# Interactive (no -Autoplay): you play seat 0; default LLM seats are 1,2,3,4.
# Pass -ManagedSeats "0,1,2,3,4" to put every civ on the LLM.
# -FullGame: Duel + Quick, stop at turn 400, watch up to 24h.
param(
    [string]$Civ5Install = "",
    [string]$ManagedSeats = "",
    [int]$WatchTimeoutSeconds = 7200,
    [int]$SidecarTimeout = 180,
    [int]$AutotestStopTurn = 20,
    [switch]$FullGame,
    [switch]$Autoplay,
    [switch]$SkipLaunch,
    [switch]$KillExisting,
    [switch]$InstallCommunityPatch,
    [switch]$RequireDiplomacy
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Civ5Ai-EnvProfile.ps1")

# Quick speed reaches 2050 around turn 330. Cap a full game past that so
# time victory can fire; the watch still ends on CIV5AI|autotest|stop.
if ($FullGame) {
    if (-not $PSBoundParameters.ContainsKey('AutotestStopTurn')) {
        $AutotestStopTurn = 400
    }
    if (-not $PSBoundParameters.ContainsKey('WatchTimeoutSeconds')) {
        $WatchTimeoutSeconds = 86400
    }
}

$Repo = Get-Civ5AiRepoRoot -FromScriptRoot $PSScriptRoot
$paths = Get-Civ5AiPaths
$Python = Resolve-Civ5AiPython
$watchScript = Join-Path $Repo "scripts\testbed\civ5_lua_log_watch.py"
$SessionId = "live-" + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()

if ([string]::IsNullOrWhiteSpace($ManagedSeats)) {
    $ManagedSeats = if ($Autoplay) { "0" } else { "1,2,3,4" }
}

if ($KillExisting) {
    Stop-Civ5Processes
}

if ($InstallCommunityPatch) {
    $installScript = Join-Path $PSScriptRoot "Invoke-Install-Civ5CommunityPatch.ps1"
    if (Test-Path -LiteralPath $installScript) {
        Write-Host "Installing Community Patch (Civ5Ai diplomacy DLL)..."
        & $installScript -Civ5Install $Civ5Install
    } else {
        Write-Warning "Invoke-Install-Civ5CommunityPatch.ps1 not found; skipping CP install."
    }
}

Write-Host "Installing jsonschema for the Civ5 sidecar..."
& $Python -m pip install jsonschema
if ($LASTEXITCODE -ne 0) {
    throw "pip install jsonschema failed (exit $LASTEXITCODE)"
}

$installRoot = if ($Civ5Install) { $Civ5Install } else { Find-Civ5InstallRoot }
$gameExe = if ($installRoot) { Join-Path $installRoot "CivilizationV.exe" } else { $null }

foreach ($root in Get-Civ5AiMyGamesRoots) {
    Ensure-Civ5ConfigIniKeys -ConfigIniPath (Join-Path $root "config.ini")
    Write-Civ5AiWindowedGraphics -MyGamesRoot $root
}

$syncArgs = @{
    ManagedSeats = $ManagedSeats
    SidecarLive = $true
    SidecarTimeout = $SidecarTimeout
    SessionId = $SessionId
    InstallInGameHooks = $true
}
if ($Autoplay) {
    $syncArgs.Autotest = $true
    $syncArgs.AutotestStopTurn = $AutotestStopTurn
}
& (Join-Path $PSScriptRoot "Invoke-Civ5AiModSync.ps1") @syncArgs

Sync-Civ5AiHostEnvKeys -Repo $Repo -Civ5AiRoot $paths.Civ5AiRoot

Write-Civ5AiRuntimeJson `
    -Civ5AiRoot $paths.Civ5AiRoot `
    -SessionId $SessionId `
    -Python $Python `
    -Repo $Repo `
    -SidecarLive 1 `
    -SidecarTimeoutSeconds $SidecarTimeout

Assert-Civ5AiLiveSidecarReady -Civ5AiRoot $paths.Civ5AiRoot -Civ5AiModRoot $paths.Civ5AiModRoot

if ($installRoot) {
    Install-Civ5AiDlcPack -RepoRoot $Repo -Civ5Install $installRoot
    Install-Civ5AiFrontEndHooks -RepoRoot $Repo -Civ5Install $installRoot
    if ($Autoplay) {
        Install-Civ5AutomationScript -RepoRoot $Repo -Civ5Install $installRoot
    }
    $installConfig = Join-Path $installRoot "config.ini"
    if (Test-Path -LiteralPath $installConfig) {
        Ensure-Civ5ConfigIniKeys -ConfigIniPath $installConfig
    }
} else {
    Write-Host "Civ5 install not found. Set CIV5_INSTALL or pass -Civ5Install."
}

if ($SkipLaunch) {
    Write-Host "SkipLaunch: setup complete. SessionId=$SessionId ManagedSeats=$ManagedSeats Autoplay=$Autoplay"
    return
}

if (-not $gameExe -or -not (Test-Path -LiteralPath $gameExe)) {
    throw "Cannot launch: CivilizationV.exe not found. Set CIV5_INSTALL to your Civ5 folder."
}

$luaLog = $paths.LuaLog
$logOffset = 0
if (Test-Path -LiteralPath $luaLog) {
    $logOffset = (Get-Item -LiteralPath $luaLog).Length
}

$env:CIV5AI_AUTOSTART = '1'
$env:PYTHONUNBUFFERED = '1'
if ($Autoplay) {
    Write-Host ('Launching autoplay LLM (seats ' + $ManagedSeats + ', stop turn ' + $AutotestStopTurn + ', Duel/Quick): ' + $gameExe)
    Write-Host ('SessionId=' + $SessionId + ' ManagedSeats=' + $ManagedSeats + ' WatchTimeoutSeconds=' + $WatchTimeoutSeconds)
    Start-Process -FilePath $gameExe -ArgumentList "-Automation", "RunCiv5AiAutoplay.lua"
} else {
    Write-Host ('Launching live play (LLM seats ' + $ManagedSeats + '): ' + $gameExe)
    Write-Host ('SessionId=' + $SessionId + ' ManagedSeats=' + $ManagedSeats)
    Start-Process -FilePath $gameExe
}

if (-not (Wait-Civ5Process -TimeoutSeconds 120)) {
    throw "CivilizationV.exe did not start within 120s"
}

$watchArgs = @(
    $watchScript,
    "--log", $luaLog,
    "--from-offset", $logOffset,
    "--timeout", $WatchTimeoutSeconds,
    "--bridge",
    "--repo", $Repo,
    "--civ5ai-root", $paths.Civ5AiRoot,
    "--gates", "G0,G1,G2",
    "--keep-watching"
)
if ($Autoplay) {
    $watchArgs += "--require-stop"
    $watchArgs += "--require-apply"
}

if ($RequireDiplomacy) {
    $watchArgs += "--require-diplomacy"
}

Write-Host "Watching Lua.log from offset $logOffset (sidecar live, seats $ManagedSeats) ..."
& $Python @watchArgs
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Host "=== Last CIV5AI lines ==="
    if (Test-Path -LiteralPath $luaLog) {
        Get-Content -LiteralPath $luaLog -Tail 200 | Where-Object { $_ -match "CIV5AI" }
    }
    throw "Civ5Ai live play watch failed (exit $exitCode)"
}

Write-Host "Live watch finished. CivilizationV may still be running. SessionId=$SessionId"
