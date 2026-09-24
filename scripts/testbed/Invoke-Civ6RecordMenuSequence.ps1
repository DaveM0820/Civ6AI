# Record a full Civ6 bootstrap click path into civ6_menu_sequence.json
param(
    [int]$TimeoutSeconds = 600,
    [switch]$ReplayTest
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Civ6Ai-EnvProfile.ps1")

$Python = Resolve-Civ6AiPython
Ensure-Civ6UiAutomationDeps -PythonExe $Python

$script = Join-Path $PSScriptRoot "civ6_record_menu_sequence.py"
$args = @("--timeout", $TimeoutSeconds)
if ($ReplayTest) { $args += "--replay-test" }

& $Python $script @args
if ($LASTEXITCODE -ne 0) { throw "Menu sequence recording failed" }

Write-Host "Done. Sequence saved to scripts\testbed\civ6_menu_sequence.json"
Write-Host "Next autotest run will replay your recorded clicks."
