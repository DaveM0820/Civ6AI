# Copy DEST\mod\Civ6Ai -> OneDrive and Documents My Games Mods\Civ6Ai (with backup)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Src = Join-Path $Root "mod\Civ6Ai"
if (-not (Test-Path $Src)) { throw "Missing $Src" }
$Meier = "Sid Meier's Civilization VI"
$Targets = @(
  (Join-Path $env:USERPROFILE "OneDrive\Documents\My Games\$Meier\Mods\Civ6Ai"),
  (Join-Path $env:USERPROFILE "Documents\My Games\$Meier\Mods\Civ6Ai")
)
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
foreach ($t in $Targets) {
  $parent = Split-Path -Parent $t
  $myGames = Split-Path -Parent (Split-Path -Parent $parent)
  if (-not (Test-Path $myGames) -and -not (Test-Path (Split-Path -Parent $myGames))) {
    Write-Host "Skip (My Games path missing): $t"
    continue
  }
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  if (Test-Path $t) {
    $backup = "$t.bak-$stamp"
    if (Test-Path $backup) { Remove-Item -Recurse -Force $backup }
    Move-Item -Force $t $backup
    Write-Host "Backup -> $backup"
  }
  Copy-Item -Recurse -Force $Src $t
  $count = (Get-ChildItem -Recurse -File $t).Count
  Write-Host "Installed $count files -> $t"
}
