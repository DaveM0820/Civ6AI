# Deploy Civ6Ai mod, refresh mod database, and verify installation.
param(
    [switch]$Autotest,
    [int]$AutotestStopTurn = 20,
    [string]$ManagedSeats = "0,1,2,3,4",
    [int]$SidecarTimeout = 120
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Civ6Ai-EnvProfile.ps1")

& (Join-Path $PSScriptRoot "Invoke-Civ6AiModSync.ps1") `
    -Autotest:$Autotest `
    -AutotestStopTurn $AutotestStopTurn `
    -ManagedSeats $ManagedSeats `
    -SidecarTimeout $SidecarTimeout `
    -RefreshModDatabase

$paths = Get-Civ6AiPaths
$modinfo = Join-Path $paths.Civ6AiModRoot "Civ6Ai.modinfo"
$xmlCount = (Get-ChildItem -LiteralPath (Join-Path $paths.Civ6AiModRoot "InGame") -Filter "*.xml").Count

Write-Host ""
Write-Host "Civ6Ai mod deployed:"
Write-Host ('  ' + $paths.Civ6AiModRoot)
Write-Host ('  modinfo: ' + (Test-Path -LiteralPath $modinfo))
Write-Host ('  InGame xml stubs: ' + $xmlCount)
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Fully quit Civilization VI (not just main menu)."
Write-Host "  2. Relaunch the game."
Write-Host "  3. Main menu -> Additional Content -> Installed (not Subscribed)."
Write-Host "  4. Enable Civ6Ai (teaser: LLM AI host Civ4AI)."
Write-Host "  5. Start or load a game."
