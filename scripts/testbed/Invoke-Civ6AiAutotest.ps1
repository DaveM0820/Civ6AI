# Civ VI autotest harness: offline tests, env, mod sync, launch, UI bootstrap, stall watchdog.
param(
    [int]$StopTurn = 20,
    [int]$Players = 4,
    [string]$ManagedSeats = "0,1,2,3",
    [string]$MapType = "Islands",
    [string]$MapSize = "Small",
    [string]$GameSpeed = "Online",
    [switch]$SkipOfflineTests,
    [switch]$KillExisting,
    [switch]$BootstrapSave,
    [switch]$SkipUiBootstrap,
    [switch]$SidecarLive,
    [switch]$FastEndTurn,
    [switch]$SkipModSync,
    [string]$SessionId = "",
    [int]$WatchTimeoutSeconds = 0,
    [int]$StallSeconds = 300,
    [int]$EarlyCheckSeconds = 60,
    [int]$ScreenshotCooldownSeconds = 45,
    [int]$BootstrapTimeoutSeconds = 90,
    [int]$SidecarTimeout = 60
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Civ6Ai-EnvProfile.ps1")

function Invoke-Civ6AiPython {
    param([Parameter(Mandatory = $true)][string[]]$ArgumentList)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Python @ArgumentList 2>&1 | ForEach-Object { Write-Host $_ }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    return $code
}

$Repo = Get-Civ6AiRepoRoot -FromScriptRoot $PSScriptRoot
$paths = Get-Civ6AiPaths
$Python = Resolve-Civ6AiPython
Ensure-Civ6UiAutomationDeps -PythonExe $Python

if ($KillExisting) {
    Write-Host "Stopping existing Civ6 processes before mod sync..."
    Stop-Civ6Processes
}

if (-not $SkipOfflineTests) {
    Write-Host "Running Civ6 offline unit tests..."
    $offlineExit = Invoke-Civ6AiPython -ArgumentList @(
        "-m", "unittest", "discover", "-s", (Join-Path $Repo "sidecar\tests"), "-p", "test_civ6*.py", "-v"
    )
    if ($offlineExit -ne 0) { throw "Civ6 offline tests failed" }
}

Write-Civ6AiAutotestEnv -StopTurn $StopTurn -ManagedSeats $ManagedSeats -SidecarLive:$(if ($SidecarLive) { 1 } else { 0 }) -FastEndTurn:$(if ($FastEndTurn) { 1 } else { 0 })
Write-Civ6AiAutotestGraphics -AppOptionsPath $paths.AppOptions
$sessionId = if ($SessionId) { $SessionId } else { New-Civ6AiSessionId }
Write-Host "Autotest session id: $sessionId"

$startupLogScript = Join-Path $Repo "scripts\testbed\civ6_startup_log.py"
Invoke-Civ6AiPython -ArgumentList @(
    $startupLogScript,
    "--civ6ai-root", $paths.Civ6AiRoot,
    "--lua-log", $paths.LuaLog,
    "--event", "harness_start",
    "--session-id", $sessionId
) | Out-Null

if (-not $SkipModSync) {
    & (Join-Path $PSScriptRoot "Invoke-Civ6AiModSync.ps1") -Autotest -AutotestStopTurn $StopTurn -ManagedSeats $ManagedSeats -SidecarTimeout $SidecarTimeout -RefreshModDatabase -SidecarLive:$SidecarLive -FastEndTurn:$FastEndTurn -SessionId $sessionId
}
& (Join-Path $PSScriptRoot "Invoke-Civ6AiConfigure.ps1") -SkipModSync

$sidecarPollScript = Join-Path $Repo "scripts\testbed\civ6_sidecar_poll.py"
$sidecarPollArgs = @($sidecarPollScript, "--civ6ai-root", $paths.Civ6AiRoot, "--lua-log", $paths.LuaLog, "--repo", $Repo)
$sidecarPoll = Start-Process -FilePath $Python -ArgumentList $sidecarPollArgs -PassThru -WindowStyle Hidden
Write-Host "Started sidecar job poller (pid $($sidecarPoll.Id))"

$bootstrapDir = Join-Path $paths.Civ6AiRoot "autotest"
New-Item -ItemType Directory -Force -Path $bootstrapDir | Out-Null

if ($BootstrapSave) {
    $bootstrapSave = Join-Path $paths.SavesSingle "civ6ai_autotest.Civ6Save"
    if (Test-Path -LiteralPath $bootstrapSave) {
        Copy-Item -LiteralPath $bootstrapSave -Destination (Join-Path $bootstrapDir "bootstrap.Civ6Save") -Force
        Write-Host "Copied bootstrap save to $($bootstrapDir)\bootstrap.Civ6Save"
    } else {
        Write-Host ('Bootstrap save not found at ' + $bootstrapSave)
    }
}

& (Join-Path $PSScriptRoot "Invoke-Civ6AiLaunch.ps1") -KillExisting:$KillExisting -WaitForProcess

if (-not $SkipUiBootstrap) {
    Write-Host "Running UI bootstrap (menus -> custom game or bootstrap save)..."
    $bootstrapScript = Join-Path $Repo "scripts\testbed\civ6_autotest_bootstrap.py"
    $bootstrapArgs = @(
        $bootstrapScript,
        "--civ6ai-root", $paths.Civ6AiRoot,
        "--lua-log", $paths.LuaLog,
        "--saves-single", $paths.SavesSingle,
        "--no-prefer-load",
        "--load-timeout", "180"
    )
    $bootstrapExit = Invoke-Civ6AiPython -ArgumentList $bootstrapArgs
    if ($bootstrapExit -ne 0) {
        $auditDir = Join-Path $bootstrapDir "bootstrap_audit"
        if (Test-Path -LiteralPath $auditDir) {
            Write-Host ('Bootstrap audit screenshots: ' + $auditDir)
        }
        if ($sidecarPoll -and -not $sidecarPoll.HasExited) {
            Stop-Process -Id $sidecarPoll.Id -Force -ErrorAction SilentlyContinue
        }
        throw "UI bootstrap failed (exit $bootstrapExit). Check bootstrap_audit screenshots."
    }
    Write-Host "UI bootstrap complete."
} else {
    Write-Host ('SkipUiBootstrap: ensure a civ6ai-enabled game is already in progress.')
}

Write-Host ('Autotest running until turn ' + $StopTurn + ' or stall detected.')
Write-Host ('Early progression check: ' + $EarlyCheckSeconds + 's after game start.')
Write-Host ('Stall watchdog: screenshot after ' + $StallSeconds + 's without progress.')

$watchdog = Join-Path $Repo "scripts\testbed\civ6_autotest_watchdog.py"
$watchArgs = @(
    $watchdog,
    "--civ6ai-root", $paths.Civ6AiRoot,
    "--lua-log", $paths.LuaLog,
    "--timeout-seconds", $WatchTimeoutSeconds,
    "--stall-seconds", $StallSeconds,
    "--early-check-seconds", $EarlyCheckSeconds,
    "--screenshot-cooldown", $ScreenshotCooldownSeconds,
    "--stop-turn", $StopTurn
)
Write-Host "Running stall watchdog..."
$watchExit = Invoke-Civ6AiPython -ArgumentList $watchArgs

if ($watchExit -eq 0) {
    Write-Host "Autotest session complete."
    & (Join-Path $PSScriptRoot "Invoke-Civ6AiAnalyze.ps1")
    if ($sidecarPoll -and -not $sidecarPoll.HasExited) {
        Stop-Process -Id $sidecarPoll.Id -Force -ErrorAction SilentlyContinue
    }
    exit 0
}

$stallDir = Join-Path $paths.Civ6AiRoot "autotest\stall_screenshots"
if (Test-Path -LiteralPath $stallDir) {
    $latest = Get-ChildItem -LiteralPath $stallDir -Directory | Sort-Object Name -Descending | Select-Object -First 1
    if ($latest) {
        Write-Host ('Stall screenshots: ' + $latest.FullName)
        Write-Host 'Check fullscreen.png and window_*.png for blocking UI (TOS, mod dialog, main menu).'
    }
}
Write-Host "Watchdog ended without session_summary - run Invoke-Civ6AiAnalyze.ps1 if partial data exists."
if ($sidecarPoll -and -not $sidecarPoll.HasExited) {
    Stop-Process -Id $sidecarPoll.Id -Force -ErrorAction SilentlyContinue
}
exit $watchExit
