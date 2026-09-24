# Gate 2 seat-type experiment: sync, launch, watch seat-experiment.jsonl.
param(
    [switch]$LaunchGame,
    [switch]$KillExisting,
    [int]$WatchSeconds = 600,
    [string]$PlayerDir = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Civ6Ai-EnvProfile.ps1")

$repo = Get-Civ6AiRepoRoot
$paths = Get-Civ6AiPaths
$python = Resolve-Civ6AiPython

& (Join-Path $PSScriptRoot "Invoke-Civ6AiConfigure.ps1") -SeatExperiment

Write-Host @"
Seat experiment enabled (SeatExperiment=1 in Civ6Ai_Paths.lua).

In-game setup:
  1. Enable Civ6Ai in Additional Content
  2. New SP game: you + at least one AI major
  3. Play 10-20 turns (managed AI seats log each turn)
"@

if ($LaunchGame) {
    & (Join-Path $PSScriptRoot "Invoke-Civ6AiLaunch.ps1") -KillExisting:$KillExisting -WaitForProcess
}

if ($PlayerDir) {
    $logPath = Join-Path $PlayerDir "seat-experiment.jsonl"
} else {
    $logPath = Join-Path $paths.Civ6AiRoot "sessions\default\PLAYER_1\seat-experiment.jsonl"
}

Write-Host "Watching session artifacts (timeout ${WatchSeconds}s)..."
$watchScript = Join-Path $PSScriptRoot "civ6_session_watch.py"
& $python $watchScript --civ6ai-root $paths.Civ6AiRoot --timeout-seconds $WatchSeconds --require-seat-log

if (Test-Path -LiteralPath $logPath) {
    Write-Host "Analyzing $logPath"
    & $python (Join-Path $repo "scripts\testbed\civ6_seat_experiment_analyze.py") $logPath
} else {
    Write-Host "No seat-experiment log yet at $logPath"
    Write-Host "After playing turns, analyze manually:"
    Write-Host "  python scripts/testbed/civ6_seat_experiment_analyze.py `"$logPath`""
}
