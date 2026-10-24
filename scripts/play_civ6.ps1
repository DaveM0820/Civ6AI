# Start the Civ6Ai helpers (if not already running) and then launch Civilization VI.
# Use this instead of the Steam/desktop shortcut so no game starts without helpers.
# The helpers detect a new game by themselves (scripts/testbed/civ6_new_game.py),
# and the watchdog respawns a helper that dies, so no --new-session is needed.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
python scripts/start_live.py | Out-Host   # exits 1 harmlessly when helpers already run
Start-Process "steam://rungameid/289070"
