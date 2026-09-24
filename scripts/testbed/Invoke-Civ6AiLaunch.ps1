# Launch Civilization VI (Steam or direct EXE).
param(
    [switch]$KillExisting,
    [switch]$WaitForProcess,
    [int]$ProcessTimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Civ6Ai-EnvProfile.ps1")

if ($KillExisting) {
    Write-Host "Stopping existing Civ6 processes..."
    Stop-Civ6Processes
}

if (Test-Civ6ProcessRunning) {
    Write-Host "Civ6 process already running."
} else {
    $steamUrl = "steam://run/289070"
    Write-Host "Launching via $steamUrl"
    Start-Process $steamUrl
    if ($WaitForProcess) {
        $ok = Wait-Civ6Process -TimeoutSeconds $ProcessTimeoutSeconds
        if (-not $ok) {
            $exe = Find-Civ6GameExe
            if ($exe) {
                Write-Host ('Steam launch slow - trying direct EXE: ' + $exe)
                Start-Process -FilePath $exe
                $ok = Wait-Civ6Process -TimeoutSeconds $ProcessTimeoutSeconds
            }
        }
        if (-not $ok) {
            throw "Civ6 process did not start within ${ProcessTimeoutSeconds}s"
        }
        Write-Host "Civ6 process detected."
    }
}

Write-Host "Launch step complete."
