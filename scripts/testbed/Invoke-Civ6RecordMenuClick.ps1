# Record a manual click in Civ6 into civ6_menu_positions.json
param(
    [string]$Key = "begin_game",
    [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Civ6Ai-EnvProfile.ps1")

$Python = Resolve-Civ6AiPython
Ensure-Civ6UiAutomationDeps -PythonExe $Python

$script = Join-Path $PSScriptRoot "civ6_record_menu_click.py"
& $Python $script --key $Key --timeout $TimeoutSeconds
if ($LASTEXITCODE -ne 0) { throw "Click recording failed" }

Write-Host "Done. Position saved to scripts\testbed\civ6_menu_positions.json"
