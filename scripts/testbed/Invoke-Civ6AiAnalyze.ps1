# Run Civ VI autotest analyzers on the latest or specified session.
param(
    [string]$SessionId = "",
    [string]$Civ6AiRoot = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Civ6Ai-EnvProfile.ps1")

$paths = Get-Civ6AiPaths
if ($Civ6AiRoot) { $paths.Civ6AiRoot = $Civ6AiRoot }
$Repo = Get-Civ6AiRepoRoot -FromScriptRoot $PSScriptRoot
$Python = Resolve-Civ6AiPython
$sessionsRoot = Join-Path $paths.Civ6AiRoot "sessions"

if (-not $SessionId) {
    $summary = Join-Path $paths.Civ6AiRoot "autotest\session_summary.json"
    if (Test-Path -LiteralPath $summary) {
        $payload = Get-Content -LiteralPath $summary -Raw | ConvertFrom-Json
        $SessionId = $payload.session_id
    }
    if (-not $SessionId) {
        $latest = Get-ChildItem -LiteralPath $sessionsRoot -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
        if ($latest) { $SessionId = $latest.Name }
    }
}

if (-not $SessionId) {
    throw "No session found under $sessionsRoot"
}

$sessionDir = Join-Path $sessionsRoot $SessionId
if (-not (Test-Path -LiteralPath $sessionDir)) {
    throw "Session directory not found: $sessionDir"
}

$analyze = Join-Path $Repo "sidecar\civ6_autotest_analyze.py"
$timeline = Join-Path $Repo "scripts\testbed\civ6_player_timeline.py"
$autotestLog = Join-Path $paths.Civ6AiRoot "autotest\autotest.log"
$reportPath = Join-Path $paths.Civ6AiRoot "autotest\report.json"

& $Python $analyze $sessionDir --autotest-log $autotestLog --output $reportPath
foreach ($playerDir in Get-ChildItem -LiteralPath $sessionDir -Directory -Filter "PLAYER_*") {
    & $Python $timeline $playerDir.FullName
}
Write-Host "Analysis complete for session $SessionId"
Write-Host "  report: $reportPath"
