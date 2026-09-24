# Civ5Ai unattended autotest: LLM on the human seat, Community Patch on the rest.
# Pass -ManagedSeats "0,1,2,3,4" later to put the other civs on the LLM too.
# Prerequisites: Civ5 + BNW, API key in civ5ai/host.env, patched CP DLL (see Invoke-Build-Civ5CommunityPatch.ps1).
param(
    [string]$Civ5Install = "",
    [string]$ManagedSeats = "0",
    [int]$StopTurn = 20,
    [int]$WatchTimeoutSeconds = 7200,
    [int]$SidecarTimeout = 180,
    [switch]$SkipLaunch,
    [switch]$KillExisting,
    [switch]$SkipCommunityPatchInstall,
    [switch]$RequireDiplomacy,
    [switch]$SetupOnly,
    [switch]$FullGame
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Civ5Ai-EnvProfile.ps1")

$Repo = Get-Civ5AiRepoRoot -FromScriptRoot $PSScriptRoot
$paths = Get-Civ5AiPaths

Write-Host "=== Civ5Ai LLM autotest ==="
Write-Host "LLM seats: $ManagedSeats | Stop turn: $StopTurn | FullGame: $FullGame | Sidecar: live"

if ($KillExisting) {
    Stop-Civ5Processes
}

if (-not $SkipCommunityPatchInstall) {
    $installScript = Join-Path $PSScriptRoot "Invoke-Install-Civ5CommunityPatch.ps1"
    if (Test-Path -LiteralPath $installScript) {
        Write-Host "Installing Community Patch with Civ5Ai diplomacy DLL..."
        try {
            & $installScript -Civ5Install $Civ5Install
        } catch {
            Write-Warning "Community Patch install failed: $_"
            Write-Warning "Diplomacy APIs require a patched CvGameCore_Expansion2.dll. Build with Invoke-Build-Civ5CommunityPatch.ps1"
        }
    }
}

$liveArgs = @{
    Civ5Install = $Civ5Install
    Autoplay = $true
    ManagedSeats = $ManagedSeats
    SidecarTimeout = $SidecarTimeout
}
if ($FullGame) {
    $liveArgs.FullGame = $true
    if ($PSBoundParameters.ContainsKey('StopTurn')) {
        $liveArgs.AutotestStopTurn = $StopTurn
    }
    if ($PSBoundParameters.ContainsKey('WatchTimeoutSeconds')) {
        $liveArgs.WatchTimeoutSeconds = $WatchTimeoutSeconds
    }
} else {
    $liveArgs.AutotestStopTurn = $StopTurn
    $liveArgs.WatchTimeoutSeconds = $WatchTimeoutSeconds
}
if ($SkipLaunch -or $SetupOnly) {
    $liveArgs.SkipLaunch = $true
}
if ($KillExisting) {
    $liveArgs.KillExisting = $true
}
if ($RequireDiplomacy) {
    $liveArgs.RequireDiplomacy = $true
}

& (Join-Path $PSScriptRoot "Invoke-Civ5AiLivePlay.ps1") @liveArgs

if ($SetupOnly) {
    Write-Host "Setup complete. Launch manually or re-run without -SetupOnly."
}
