# Thin wrappers — prefer python scripts (they hide child consoles on Windows)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
python scripts\start_live.py @args
