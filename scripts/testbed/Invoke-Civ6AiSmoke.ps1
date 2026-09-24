# Civ6AI smoke: offline tests + optional game launch.
param(
    [switch]$WithGame,
    [switch]$KillExisting
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Civ6Ai-EnvProfile.ps1")

$repo = Get-Civ6AiRepoRoot
$paths = Get-Civ6AiPaths
$python = Resolve-Civ6AiPython

Write-Host "=== Civ6AI offline tests ==="
& (Join-Path $PSScriptRoot "Invoke-Civ6AiOfflineTests.ps1")

Write-Host "=== Civ6AI configure ==="
& (Join-Path $PSScriptRoot "Invoke-Civ6AiConfigure.ps1")

if (-not $WithGame) {
    Write-Host "Smoke complete (offline only). Use -WithGame to launch Civ6."
    return
}

Write-Host "=== Civ6AI launch ==="
& (Join-Path $PSScriptRoot "Invoke-Civ6AiLaunch.ps1") `
    -KillExisting:$KillExisting `
    -WaitForProcess

Write-Host "=== Lua.log tail (CIV6AI markers) ==="
if (Test-Path -LiteralPath $paths.LuaLog) {
    Get-Content -LiteralPath $paths.LuaLog -Tail 30 | Where-Object { $_ -match "CIV6AI" }
} else {
    Write-Host "No Lua.log yet at $($paths.LuaLog)"
}

Write-Host "Smoke complete."
