# Configure Civ6AI: sync mod, host.env bootstrap.
param(
    [switch]$SkipModSync,
    [switch]$SeatExperiment,
    [int]$SidecarTimeout = 45
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Civ6Ai-EnvProfile.ps1")

$repo = Get-Civ6AiRepoRoot
$paths = Get-Civ6AiPaths

Write-Host ('My Games: ' + $paths.MyGames)
Write-Host ('AppOptions: ' + $paths.AppOptions)

if (-not $SkipModSync) {
    $syncArgs = @()
    if ($SeatExperiment) { $syncArgs += "-SeatExperiment" }
    if ($SidecarTimeout) { $syncArgs += "-SidecarTimeout"; $syncArgs += $SidecarTimeout }
    & (Join-Path $PSScriptRoot "Invoke-Civ6AiModSync.ps1") @syncArgs
}

if (-not (Test-Path -LiteralPath $paths.Civ6AiModRoot)) {
    throw "Civ6Ai mod not deployed to $($paths.Civ6AiModRoot)"
}

$hostExample = Join-Path $repo "fixtures\civ6\host.env.example"
$hostTarget = Join-Path $paths.Civ6AiRoot "host.env"
New-Item -ItemType Directory -Force -Path $paths.Civ6AiRoot | Out-Null
if (-not (Test-Path -LiteralPath $hostTarget)) {
    Copy-Item -LiteralPath $hostExample -Destination $hostTarget
    Write-Host ('Created host.env at ' + $hostTarget)
}

Write-Host "Configure complete."
Write-Host "Civ6Ai mod uses EnabledByDefault; autotest harness enables via mod sync."
