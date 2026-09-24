# Civ6AI standard workflow: offline tests + mod sync, optionally in-game autotest.
# Use after every substantive Civ6Ai / civ6 sidecar change before considering work done.
param(
    [switch]$Live,
    [switch]$QuickLive,
    [int]$StopTurn = 10,
    [string]$ManagedSeats = "0,1,2,3",
    [switch]$SidecarLive,
    [switch]$FastEndTurn,
    [switch]$KillExisting,
    [switch]$SkipOfflineTests,
    [switch]$SkipModSync,
    [switch]$SkipUiBootstrap,
    [int]$WatchTimeoutSeconds = 0,
    [int]$StallSeconds = 0,
    [int]$EarlyCheckSeconds = 60,
    [int]$SidecarTimeout = 60
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Civ6Ai-EnvProfile.ps1")

$repo = Get-Civ6AiRepoRoot -FromScriptRoot $PSScriptRoot
$paths = Get-Civ6AiPaths

if (($Live -or $QuickLive) -and $KillExisting) {
    Write-Host "Stopping existing Civ6 processes before sync..."
    Stop-Civ6Processes
}

if (-not $SkipOfflineTests) {
    Write-Host "=== Civ6AI offline tests ==="
    & (Join-Path $PSScriptRoot "Invoke-Civ6AiOfflineTests.ps1")
}

$sessionId = ""
$syncAutotest = $Live -or $QuickLive

if (-not $SkipModSync) {
    Write-Host "=== Civ6AI mod sync ==="
    if ($syncAutotest) {
        $sessionId = New-Civ6AiSessionId
        $liveStopTurn = if ($QuickLive) { 5 } else { $StopTurn }
        Write-Civ6AiAutotestEnv -StopTurn $liveStopTurn -ManagedSeats $ManagedSeats -SidecarLive:$(if ($SidecarLive) { 1 } else { 0 }) -FastEndTurn:$(if ($FastEndTurn) { 1 } else { 0 }) -SessionId $sessionId
        & (Join-Path $PSScriptRoot "Invoke-Civ6AiModSync.ps1") `
            -Autotest `
            -AutotestStopTurn $liveStopTurn `
            -ManagedSeats $ManagedSeats `
            -SidecarTimeout $SidecarTimeout `
            -RefreshModDatabase `
            -SidecarLive:$SidecarLive `
            -FastEndTurn:$FastEndTurn `
            -SessionId $sessionId
    } else {
        & (Join-Path $PSScriptRoot "Invoke-Civ6AiModSync.ps1") -RefreshModDatabase -SidecarLive:$SidecarLive
    }
    Write-Host "Mod synced to $($paths.Civ6AiModRoot)"
} else {
    Write-Host "Skipped mod sync (-SkipModSync)."
}

if (-not $Live -and -not $QuickLive) {
    Write-Host "SyncAndTest complete (offline + sync)."
    Write-Host "For in-game validation: .\scripts\testbed\Invoke-Civ6AiSyncAndTest.ps1 -Live -SidecarLive -KillExisting"
    exit 0
}

$liveStopTurn = if ($QuickLive) { 5 } else { $StopTurn }
$watchTimeout = if ($WatchTimeoutSeconds -gt 0) { $WatchTimeoutSeconds } else { 0 }
$stallTimeout = if ($StallSeconds -gt 0) { $StallSeconds } elseif ($QuickLive) { 600 } else { 300 }

Write-Host "=== Civ6AI live autotest (stop turn $liveStopTurn) ==="
$autotestArgs = @{
    StopTurn = $liveStopTurn
    ManagedSeats = $ManagedSeats
    SkipOfflineTests = $true
    SkipModSync = $true
    KillExisting = $KillExisting
    SidecarLive = $SidecarLive
    FastEndTurn = $FastEndTurn
    WatchTimeoutSeconds = $watchTimeout
    StallSeconds = $stallTimeout
    EarlyCheckSeconds = $EarlyCheckSeconds
    SkipUiBootstrap = $SkipUiBootstrap
}
if ($sessionId) {
    $autotestArgs.SessionId = $sessionId
}
& (Join-Path $PSScriptRoot "Invoke-Civ6AiAutotest.ps1") @autotestArgs
