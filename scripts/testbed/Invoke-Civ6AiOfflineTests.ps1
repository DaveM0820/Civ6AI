# Run Civ6AI offline unit tests (no game required).
param(
    [string]$Pattern = "test_civ6*.py"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Civ6Ai-EnvProfile.ps1")

$repo = Get-Civ6AiRepoRoot
$python = Resolve-Civ6AiPython

Push-Location $repo
$prevErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $python -m unittest discover -s sidecar/tests -p $Pattern -v 2>&1 | ForEach-Object { Write-Host $_ }
$code = $LASTEXITCODE
$ErrorActionPreference = $prevErrorAction
Pop-Location

if ($code -ne 0) { throw "Civ6 offline tests failed (exit $code)" }
Write-Host "Civ6 offline tests passed."
