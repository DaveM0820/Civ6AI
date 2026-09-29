# Thin wrapper: install the Civ6Ai mod (+ generated live config) via install_mod.py.
# Arguments pass through, e.g.:  .\scripts\install_mod.ps1 --managed-seats 1 --sidecar-timeout 600
$ErrorActionPreference = "Stop"
$Script = Join-Path $PSScriptRoot "install_mod.py"
if (-not (Test-Path -LiteralPath $Script)) { throw "Missing $Script" }
& python $Script @args
exit $LASTEXITCODE
