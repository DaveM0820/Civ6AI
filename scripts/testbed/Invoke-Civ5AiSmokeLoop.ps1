# Civ5Ai STEP 1: unattended turn-loop smoke (no LLM, no sidecar).
param(
    [string]$Civ5Install = "",
    [int]$StopTurn = 3,
    [int]$WatchTimeoutSeconds = 420,
    [switch]$SkipLaunch,
    [switch]$KillExisting,
    [switch]$ModsOnly,
    [switch]$RequireStopGate,
    [switch]$RequireNet,
    [switch]$RequireApply,
    [switch]$SkipAutomation,
    [switch]$FastEndTurn,
    [string]$ManagedSeats = "0"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Civ5Ai-EnvProfile.ps1")

$Repo = Get-Civ5AiRepoRoot -FromScriptRoot $PSScriptRoot
$paths = Get-Civ5AiPaths
$Python = Resolve-Civ5AiPython
$watchScript = Join-Path $Repo "scripts\testbed\civ5_lua_log_watch.py"

if ($KillExisting) {
    Stop-Civ5Processes
}

$installRoot = if ($Civ5Install) { $Civ5Install } else { Find-Civ5InstallRoot }
$gameExe = if ($installRoot) { Join-Path $installRoot "CivilizationV.exe" } else { $null }

foreach ($root in Get-Civ5AiMyGamesRoots) {
    Ensure-Civ5ConfigIniKeys -ConfigIniPath (Join-Path $root "config.ini")
    Write-Civ5AiWindowedGraphics -MyGamesRoot $root
}

if ($RequireApply -and $ManagedSeats -eq "0") {
    $ManagedSeats = "1,2,3,4"
}
if ($RequireApply -and $WatchTimeoutSeconds -lt 600) {
    $WatchTimeoutSeconds = 600
}

$syncArgs = @{
    Autotest = $true
    AutotestStopTurn = $StopTurn
    ManagedSeats = $ManagedSeats
    InstallInGameHooks = $true
}
if ($FastEndTurn) {
    $syncArgs.FastEndTurn = $true
}
& (Join-Path $PSScriptRoot "Invoke-Civ5AiModSync.ps1") @syncArgs

if (-not $ModsOnly -and $installRoot) {
    Install-Civ5AiDlcPack -RepoRoot $Repo -Civ5Install $installRoot
    Install-Civ5AiFrontEndHooks -RepoRoot $Repo -Civ5Install $installRoot
    Install-Civ5AutomationScript -RepoRoot $Repo -Civ5Install $installRoot

    $installConfig = Join-Path $installRoot "config.ini"
    if (Test-Path -LiteralPath $installConfig) {
        Ensure-Civ5ConfigIniKeys -ConfigIniPath $installConfig
    }
} elseif (-not $ModsOnly) {
    Write-Host "Civ5 install not found. Set CIV5_INSTALL or pass -Civ5Install."
    Write-Host "MODS folder was synced - use Mods menu + Community Patch for manual smoke, or install Civ5."
}

if ($SkipLaunch) {
    Write-Host "SkipLaunch: setup complete."
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
if ($SkipAutomation) {
    Write-Host ('Launching: ' + $gameExe + ' (no -Automation; FrontEnd loads Community Patch DLL)')
    Start-Process -FilePath $gameExe
} else {
    Write-Host ('Launching: ' + $gameExe + ' -Automation RunCiv5AiAutoplay.lua')
    Start-Process -FilePath $gameExe -ArgumentList "-Automation", "RunCiv5AiAutoplay.lua"
}

if (-not (Wait-Civ5Process -TimeoutSeconds 120)) {
    throw "CivilizationV.exe did not start within 120s"
}

$watchArgs = @(
    $watchScript,
    "--log", $luaLog,
    "--from-offset", $logOffset,
    "--timeout", $WatchTimeoutSeconds,
    "--repo", $Repo
)
if ($RequireApply) {
    $watchArgs += "--bridge"
}
if ($RequireStopGate) {
    $watchArgs += "--require-stop"
}
if ($RequireNet) {
    $watchArgs += "--require-net"
}
if ($RequireApply) {
    $watchArgs += "--require-apply"
}

Write-Host "Watching Lua.log from offset $logOffset ..."
& $Python @watchArgs
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Host "=== Last CIV5AI lines ==="
    if (Test-Path -LiteralPath $luaLog) {
        Get-Content -LiteralPath $luaLog -Tail 200 | Where-Object { $_ -match "CIV5AI" }
    }
    throw "Civ5Ai smoke loop failed (exit $exitCode)"
}

Write-Host "Civ5Ai smoke loop passed."
if (Test-Civ5ProcessRunning) {
    Write-Host "CivilizationV is still running. Close manually or re-run with KillExisting."
}
