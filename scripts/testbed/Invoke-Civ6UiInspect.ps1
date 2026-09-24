# OCR Civ6 UI: dump text positions and save annotated screenshot (green=OCR hits, red=saved clicks)
param(
    [string]$Filter = "",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Civ6Ai-EnvProfile.ps1")

$Python = Resolve-Civ6AiPython
Ensure-Civ6UiAutomationDeps -PythonExe $Python

$script = Join-Path $PSScriptRoot "civ6_ui_inspect.py"
$args = @($script)
if ($Filter) { $args += "--filter"; $args += $Filter }
if ($OutDir) { $args += "--out-dir"; $args += $OutDir }

& $Python @args
