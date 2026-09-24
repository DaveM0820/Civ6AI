# UI-only bootstrap: navigate Civ6 menus on an already-running game (no launch/kill).
param(
    [int]$Players = 4,
    [string]$MapType = "Islands",
    [string]$MapSize = "Small",
    [string]$GameSpeed = "Online",
    [int]$LoadTimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Civ6Ai-EnvProfile.ps1")

$Repo = Get-Civ6AiRepoRoot -FromScriptRoot $PSScriptRoot
$paths = Get-Civ6AiPaths
$Python = Resolve-Civ6AiPython
Ensure-Civ6UiAutomationDeps -PythonExe $Python

$bootstrapScript = Join-Path $Repo "scripts\testbed\civ6_autotest_bootstrap.py"
$args = @(
    $bootstrapScript,
    "--civ6ai-root", $paths.Civ6AiRoot,
    "--lua-log", $paths.LuaLog,
    "--saves-single", $paths.SavesSingle,
    "--no-prefer-load",
    "--load-timeout", $LoadTimeoutSeconds
)
& $Python @args
exit $LASTEXITCODE
