# Copy DEST\mod\Civ6Ai -> OneDrive and Documents My Games Mods\Civ6Ai
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Src = Join-Path $Root "mod\Civ6Ai"
if (-not (Test-Path $Src)) { throw "Missing $Src" }
$Meier = "Sid Meier's Civilization VI"
$Targets = @(
  (Join-Path $env:USERPROFILE "OneDrive\Documents\My Games\$Meier\Mods\Civ6Ai"),
  (Join-Path $env:USERPROFILE "Documents\My Games\$Meier\Mods\Civ6Ai")
)
foreach ($t in $Targets) {
  $parent = Split-Path -Parent $t
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  if (Test-Path $t) { Remove-Item -Recurse -Force $t }
  Copy-Item -Recurse -Force $Src $t
  $count = (Get-ChildItem -Recurse -File $t).Count
  Write-Host "Installed $count files -> $t"
}
