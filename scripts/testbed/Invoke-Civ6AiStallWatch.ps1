# Run Civ6 autotest stall watchdog (screenshots on freeze / no progress).
param(
    [int]$TimeoutSeconds = 3600,
    [int]$StallSeconds = 90,
    [int]$ScreenshotCooldownSeconds = 60
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Civ6Ai-EnvProfile.ps1")

$Repo = Get-Civ6AiRepoRoot -FromScriptRoot $PSScriptRoot
$paths = Get-Civ6AiPaths
$Python = Resolve-Civ6AiPython
$watchdog = Join-Path $Repo "scripts\testbed\civ6_autotest_watchdog.py"

& $Python $watchdog `
    --civ6ai-root $paths.Civ6AiRoot `
    --lua-log $paths.LuaLog `
    --timeout-seconds $TimeoutSeconds `
    --stall-seconds $StallSeconds `
    --screenshot-cooldown $ScreenshotCooldownSeconds
