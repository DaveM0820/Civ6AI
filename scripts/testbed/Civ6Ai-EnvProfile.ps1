# Shared Civ6AI paths and helpers for testbed launch scripts.

function Ensure-Civ6UiAutomationDeps {
    param([string]$PythonExe = (Resolve-Civ6AiPython))
    $req = Join-Path $PSScriptRoot "requirements-civ6-ui.txt"
    if (-not (Test-Path -LiteralPath $req)) { return }
    & $PythonExe -m pip install -r $req -q
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install Civ6 UI automation Python dependencies"
    }
}
function Get-Civ6AiRepoRoot {
    param([string]$FromScriptRoot = $PSScriptRoot)
    Split-Path -Parent (Split-Path -Parent $FromScriptRoot)
}

function Import-Civ6AiDotEnv {
    param([string]$RepoRoot = (Get-Civ6AiRepoRoot -FromScriptRoot $PSScriptRoot))
    $localEnv = Join-Path $RepoRoot ".env"
    if (-not (Test-Path -LiteralPath $localEnv)) { return }
    foreach ($line in Get-Content -LiteralPath $localEnv) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or ($trimmed -notmatch '=')) { continue }
        $parts = $trimmed -split '=', 2
        $name = $parts[0].Trim()
        $value = $parts[1].Trim()
        if ($name) { Set-Item -Path "Env:$name" -Value $value }
    }
}

function Import-Civ4AiApiKeysForCiv6 {
    $candidates = @(
        (Join-Path $env:USERPROFILE "OneDrive\Documents\My Games\beyond the sword\civ4ai-autotest\autotest.env"),
        (Join-Path $env:USERPROFILE "Documents\My Games\beyond the sword\civ4ai-autotest\autotest.env"),
        (Join-Path $env:USERPROFILE "OneDrive\Documents\My Games\beyond the sword\civ4ai-autotest\host.env"),
        (Join-Path $env:USERPROFILE "Documents\My Games\beyond the sword\civ4ai-autotest\host.env")
    )
    foreach ($path in $candidates) {
        if (-not (Test-Path -LiteralPath $path)) { continue }
        foreach ($line in Get-Content -LiteralPath $path) {
            $trimmed = $line.Trim()
            if (-not $trimmed -or $trimmed.StartsWith("#") -or ($trimmed -notmatch '=')) { continue }
            $parts = $trimmed -split '=', 2
            $name = $parts[0].Trim()
            $value = $parts[1].Trim()
            if ($name -match '^(GEMINI_API_KEY|OPENAI_API_KEY|GOOGLE_API_KEY|GEMINI_MODEL|CIV4AI_MODEL_PROVIDER)$') {
                $current = (Get-Item -Path "Env:$name" -ErrorAction SilentlyContinue).Value
                if (-not $current) { Set-Item -Path "Env:$name" -Value $value }
            }
        }
        if ($env:GEMINI_API_KEY -or $env:OPENAI_API_KEY) { return $path }
    }
    return $null
}

function Write-Utf8NoBom {
    param([string]$Path, [string]$Content)
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($Path, $Content, $utf8)
}

function Get-Civ6AiKnownDocuments {
    $known = [Environment]::GetFolderPath('MyDocuments')
    if ($known) { return $known }
    return (Join-Path $env:USERPROFILE "Documents")
}

function Get-Civ6AiMyGamesRoot {
    $candidates = @(
        (Join-Path (Get-Civ6AiKnownDocuments) "My Games\Sid Meier's Civilization VI"),
        (Join-Path $env:USERPROFILE "Documents\My Games\Sid Meier's Civilization VI"),
        (Join-Path $env:USERPROFILE "OneDrive\Documents\My Games\Sid Meier's Civilization VI")
    )
    foreach ($path in $candidates) {
        if (Test-Path -LiteralPath $path) { return $path }
    }
    return $candidates[0]
}

function Get-Civ6AiMyGamesRoots {
    $candidates = @(
        (Join-Path (Get-Civ6AiKnownDocuments) "My Games\Sid Meier's Civilization VI"),
        (Join-Path $env:USERPROFILE "Documents\My Games\Sid Meier's Civilization VI"),
        (Join-Path $env:USERPROFILE "OneDrive\Documents\My Games\Sid Meier's Civilization VI")
    )
    $roots = @()
    foreach ($path in $candidates) {
        if (Test-Path -LiteralPath $path) { $roots += $path }
    }
    if ($roots.Count -eq 0) { return @($candidates[0]) }
    return $roots
}

function Reset-Civ6ModDatabase {
    param([string]$MyGamesRoot = "")
    $paths = @()
    if ($MyGamesRoot) {
        $paths += Join-Path $MyGamesRoot "Mods.sqlite"
    }
    $paths += (Get-Civ6ModDatabasePath)
    foreach ($db in $paths | Select-Object -Unique) {
        if (Test-Path -LiteralPath $db) {
            Remove-Item -LiteralPath $db -Force
            Write-Host ('Removed mod database: ' + $db)
        }
    }
}

function Get-Civ6ModDatabasePath {
    return Join-Path $env:LOCALAPPDATA "Firaxis Games\Sid Meier's Civilization VI\Mods.sqlite"
}

function Resolve-Civ6LuaLog {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Firaxis Games\Sid Meier's Civilization VI\Logs\Lua.log"),
        (Join-Path (Get-Civ6AiMyGamesRoot) "Logs\Lua.log"),
        (Join-Path (Get-Civ6AiMyGamesRoot) "Firaxis Games\Sid Meier's Civilization VI\Logs\Lua.log")
    )
    foreach ($path in $candidates) {
        if (Test-Path -LiteralPath $path) { return $path }
    }
    return $candidates[0]
}

function Get-Civ6AiCanonicalDataRoot {
    return Join-Path (Get-Civ6AiMyGamesRoot) "civ6ai"
}

function Get-Civ6AiPaths {
    $myGames = Get-Civ6AiMyGamesRoot
    $firaxis = Join-Path $myGames "Firaxis Games\Sid Meier's Civilization VI"
    return @{
        MyGames = $myGames
        ModsRoot = Join-Path $myGames "Mods"
        Civ6AiModRoot = Join-Path $myGames "Mods\Civ6Ai"
        Civ6AiRoot = Get-Civ6AiCanonicalDataRoot
        AppOptions = Join-Path $firaxis "AppOptions.txt"
        LuaLog = Resolve-Civ6LuaLog
        ModDatabase = Get-Civ6ModDatabasePath
        SavesSingle = Join-Path $myGames "Saves\Single"
    }
}

function New-Civ6AiSessionId {
    return ("autotest-" + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds())
}

function Ensure-Civ6AiSessionLayout {
    param(
        [string]$Civ6AiRoot,
        [string]$SessionId,
        [string]$ManagedSeats = "0,1,2,3"
    )
    $autotestDir = Join-Path $Civ6AiRoot "autotest"
    New-Item -ItemType Directory -Force -Path $autotestDir | Out-Null
    $seats = @()
    foreach ($token in ($ManagedSeats -split ',')) {
        $trimmed = $token.Trim()
        if ($trimmed -ne "") { $seats += $trimmed }
    }
    if ($seats.Count -eq 0) { $seats = @("0", "1", "2", "3") }
    foreach ($seat in $seats) {
        $playerDir = Join-Path $Civ6AiRoot "sessions\$SessionId\PLAYER_$seat"
        New-Item -ItemType Directory -Force -Path $playerDir | Out-Null
    }
    $luaLog = Resolve-Civ6LuaLog
    if ($luaLog) {
        $logMirror = Join-Path (Split-Path -Parent $luaLog) "civ6ai"
        foreach ($seat in $seats) {
            $playerDir = Join-Path $logMirror "sessions\$SessionId\PLAYER_$seat"
            New-Item -ItemType Directory -Force -Path $playerDir | Out-Null
        }
    }
}

function Write-Civ6AiRuntimeJson {
    param(
        [string]$Civ6AiRoot,
        [string]$SessionId,
        [int]$StopTurn,
        [string]$ManagedSeats,
        [int]$SidecarLive,
        [int]$FastEndTurn,
        [string]$RepoRoot,
        [string]$PythonExe
    )
    $payload = @{
        autotest = 1
        sidecar_live = $SidecarLive
        fast_end_turn = $FastEndTurn
        managed_seats = $ManagedSeats
        stop_turn = $StopTurn
        session_id = $SessionId
        root = ($Civ6AiRoot -replace '\\', '/')
        repo = ($RepoRoot -replace '\\', '/')
        python = ($PythonExe -replace '\\', '/')
    } | ConvertTo-Json -Compress
    $runtimePath = Join-Path $Civ6AiRoot "runtime.json"
    Write-Utf8NoBom -Path $runtimePath -Content ($payload + "`n")
}

function Resolve-Civ6AiPython {
    $candidates = @()
    if ($env:CIV6AI_PYTHON) { $candidates += $env:CIV6AI_PYTHON.Trim() }
    $candidates += @(
        (Join-Path $env:USERPROFILE "miniconda3\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python314\python.exe")
    )
    try {
        $candidates += (Get-Command python -ErrorAction Stop).Source
    } catch {
        # fall through
    }
    foreach ($exe in $candidates) {
        if (-not $exe -or -not (Test-Path -LiteralPath $exe)) { continue }
        & $exe -c "import jsonschema" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return $exe }
    }
    throw "No Python interpreter with jsonschema found (pip install jsonschema)"
}

function Find-Civ6GameExe {
    $steam = Join-Path ${env:ProgramFiles(x86)} "Steam"
    $candidates = @(
        (Join-Path $steam "steamapps\common\Sid Meier's Civilization VI\Base\Binaries\Win64Steam\CivilizationVI_DX12.exe"),
        (Join-Path $steam "steamapps\common\Sid Meier's Civilization VI\Base\Binaries\Win64Steam\CivilizationVI.exe")
    )
    foreach ($exe in $candidates) {
        if (Test-Path -LiteralPath $exe) { return $exe }
    }
    return $null
}

function Test-Civ6ProcessRunning {
    $names = @("Civ6_Exe", "Civ6_Exe_Child", "CivilizationVI_DX12", "CivilizationVI")
    foreach ($name in $names) {
        if (Get-Process -Name $name -ErrorAction SilentlyContinue) { return $true }
    }
    return $false
}

function Wait-Civ6Process {
    param([int]$TimeoutSeconds = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Civ6ProcessRunning) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Stop-Civ6Processes {
    $names = @("Civ6_Exe", "Civ6_Exe_Child", "CivilizationVI_DX12", "CivilizationVI")
    foreach ($name in $names) {
        Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 3
}

function Write-Civ6AiAutotestEnv {
    param(
        [string]$Civ6AiRoot = "",
        [int]$StopTurn = 20,
        [string]$ManagedSeats = "0,1,2,3,4",
        [string]$ModelProvider = "gemini",
        [int]$SidecarLive = 0,
        [int]$FastEndTurn = 0,
        [string]$SessionId = ""
    )
    Import-Civ6AiDotEnv
    if ($SidecarLive -eq 1 -and $FastEndTurn -eq 1) {
        Write-Warning "CIV6AI_FAST_END_TURN=1 ignored while CIV6AI_SIDECAR_LIVE=1 (LLM pulse required)."
        $FastEndTurn = 0
    }
    $keySource = Import-Civ4AiApiKeysForCiv6
    if (-not $env:GEMINI_API_KEY -and $env:GOOGLE_API_KEY) {
        $env:GEMINI_API_KEY = $env:GOOGLE_API_KEY
    }
    if ($env:CIV4AI_MODEL_PROVIDER -and -not $env:CIV6AI_MODEL_PROVIDER) {
        $ModelProvider = $env:CIV4AI_MODEL_PROVIDER
    }
    $paths = Get-Civ6AiPaths
    if (-not $Civ6AiRoot) { $Civ6AiRoot = $paths.Civ6AiRoot }
    $civ6AiRoots = @(Get-Civ6AiMyGamesRoots | ForEach-Object { Join-Path $_ "civ6ai" })
    if ($civ6AiRoots -notcontains $Civ6AiRoot) { $civ6AiRoots = @($Civ6AiRoot) + $civ6AiRoots }
    $primaryAutotestEnv = Join-Path $Civ6AiRoot "autotest.env"
    $example = Join-Path (Get-Civ6AiRepoRoot -FromScriptRoot $PSScriptRoot) "fixtures\civ6\host.env.example"

    foreach ($root in $civ6AiRoots) {
        New-Item -ItemType Directory -Force -Path $root | Out-Null
        $hostEnv = Join-Path $root "host.env"
        $lines = @(
            "CIV6AI_AUTOTEST=1",
            "CIV6AI_SIDECAR_LIVE=$SidecarLive",
            "CIV6AI_FAST_END_TURN=$FastEndTurn",
            "CIV6AI_MANAGED_SEATS=$ManagedSeats",
            "CIV6AI_AUTOTEST_STOP_TURN=$StopTurn",
            "CIV6AI_MODEL_PROVIDER=$ModelProvider"
        )
        if ($SessionId) { $lines += "CIV6AI_SESSION_ID=$SessionId" }
        if ($env:GEMINI_API_KEY) { $lines += "GEMINI_API_KEY=$env:GEMINI_API_KEY" }
        if ($env:OPENAI_API_KEY) { $lines += "OPENAI_API_KEY=$env:OPENAI_API_KEY" }
        if ($env:GOOGLE_API_KEY) { $lines += "GOOGLE_API_KEY=$env:GOOGLE_API_KEY" }
        if ($env:GEMINI_MODEL) { $lines += "GEMINI_MODEL=$env:GEMINI_MODEL" }
        $lines += "CIV4AI_GEMINI_API=interactions"
        $lines += "GEMINI_THINKING_LEVEL=low"
        $autotestEnv = Join-Path $root "autotest.env"
        Set-Content -LiteralPath $autotestEnv -Value ($lines -join "`n") -Encoding UTF8
        if (-not (Test-Path -LiteralPath $hostEnv)) {
            if (Test-Path -LiteralPath $example) {
                Copy-Item -LiteralPath $example -Destination $hostEnv
            }
        }
        if ($env:GEMINI_API_KEY) {
            $hostLines = @()
            if (Test-Path -LiteralPath $hostEnv) { $hostLines = @(Get-Content -LiteralPath $hostEnv) }
            $hostLines += "GEMINI_API_KEY=$env:GEMINI_API_KEY"
            if ($env:OPENAI_API_KEY) { $hostLines += "OPENAI_API_KEY=$env:OPENAI_API_KEY" }
            Set-Content -LiteralPath $hostEnv -Value ($hostLines -join "`n") -Encoding UTF8
        }
        Write-Host "Wrote $autotestEnv"
        if ($SessionId) {
            Ensure-Civ6AiSessionLayout -Civ6AiRoot $root -SessionId $SessionId -ManagedSeats $ManagedSeats
            Write-Civ6AiRuntimeJson -Civ6AiRoot $root -SessionId $SessionId -StopTurn $StopTurn -ManagedSeats $ManagedSeats -SidecarLive $SidecarLive -FastEndTurn $FastEndTurn -RepoRoot (Get-Civ6AiRepoRoot -FromScriptRoot $PSScriptRoot) -PythonExe (Resolve-Civ6AiPython)
        }
    }

    if ($keySource) { Write-Host "API keys sourced from $keySource" }
    if (-not $env:GEMINI_API_KEY -and -not $env:OPENAI_API_KEY) {
        Write-Warning "No GEMINI_API_KEY or OPENAI_API_KEY found in repo .env or Civ4 autotest.env"
    }
    return $primaryAutotestEnv
}

function Set-Civ6IniValue {
    param(
        [string]$IniPath,
        [string]$Key,
        [string]$Value,
        [string]$Section = ""
    )
    if (-not (Test-Path -LiteralPath $IniPath)) {
        $parent = Split-Path -Parent $IniPath
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        Set-Content -LiteralPath $IniPath -Value "" -Encoding UTF8
    }
    $lines = @(Get-Content -LiteralPath $IniPath -ErrorAction SilentlyContinue)
    $newLine = "$Key $Value"
    $pattern = "^\s*$Key\s+"
    $found = $false
    $out = @()
    $inSection = (-not $Section)
    foreach ($line in $lines) {
        if ($Section -and $line -match '^\s*\[([^\]]+)\]\s*$') {
            $inSection = ($matches[1] -eq $Section)
        }
        if (($inSection -or -not $Section) -and $line -match $pattern) {
            $out += $newLine
            $found = $true
        } else {
            $out += $line
        }
    }
    if (-not $found) {
        if ($Section) {
            $out += ""
            $out += "[$Section]"
            $out += $newLine
        } else {
            $out += $newLine
        }
    }
    Set-Content -LiteralPath $IniPath -Value $out -Encoding UTF8
}

function Set-Civ6AppOption {
    param(
        [string]$AppOptionsPath,
        [string]$Key,
        [string]$Value
    )
    Set-Civ6IniValue -IniPath $AppOptionsPath -Key $Key -Value $Value
}

function Get-Civ6MenuSequenceRenderSize {
    $repo = Get-Civ6AiRepoRoot -FromScriptRoot $PSScriptRoot
    $seqPath = Join-Path $repo "scripts\testbed\civ6_menu_sequence.json"
    if (-not (Test-Path -LiteralPath $seqPath)) {
        return @{ Width = 1280; Height = 720 }
    }
    try {
        $seq = Get-Content -LiteralPath $seqPath -Raw | ConvertFrom-Json
        $w = if ($seq.ref_w) { [int]$seq.ref_w } else { 1280 }
        $h = if ($seq.ref_h) { [int]$seq.ref_h } else { 720 }
        return @{ Width = $w; Height = $h }
    } catch {
        return @{ Width = 1280; Height = 720 }
    }
}

function Write-Civ6AiAutotestGraphics {
    param([string]$AppOptionsPath = "")
    $render = Get-Civ6MenuSequenceRenderSize
    $renderW = "$($render.Width)"
    $renderH = "$($render.Height)"
    $appPaths = @()
    if ($AppOptionsPath) { $appPaths += $AppOptionsPath }
    $localApp = Join-Path $env:LOCALAPPDATA "Firaxis Games\Sid Meier's Civilization VI\AppOptions.txt"
    if (Test-Path -LiteralPath $localApp) { $appPaths += $localApp }
    $appPaths = $appPaths | Select-Object -Unique
    foreach ($path in $appPaths) {
        Set-Civ6IniValue -IniPath $path -Key "FullScreen" -Value "0"
        Set-Civ6IniValue -IniPath $path -Key "WindowWidth" -Value $renderW
        Set-Civ6IniValue -IniPath $path -Key "WindowHeight" -Value $renderH
        Set-Civ6IniValue -IniPath $path -Key "RenderWidth" -Value $renderW
        Set-Civ6IniValue -IniPath $path -Key "RenderHeight" -Value $renderH
        Set-Civ6IniValue -IniPath $path -Key "GraphicsQuality" -Value "0"
        Set-Civ6IniValue -IniPath $path -Key "PlayIntroVideo" -Value "0"
        Set-Civ6IniValue -IniPath $path -Key "EnablePausedShellMovies" -Value "0"
    }
    $userOptions = Join-Path $env:LOCALAPPDATA "Firaxis Games\Sid Meier's Civilization VI\UserOptions.txt"
    if (-not (Test-Path -LiteralPath $userOptions)) {
        New-Item -ItemType File -Force -Path $userOptions | Out-Null
    }
    Set-Civ6IniValue -IniPath $userOptions -Key "TutorialLevel" -Value "-1" -Section "Tutorial"
    Set-Civ6IniValue -IniPath $userOptions -Key "HasChosenTutorialLevel" -Value "1" -Section "Tutorial"
    Set-Civ6IniValue -IniPath $userOptions -Key "HasSeenXP1FeaturesScreen" -Value "1" -Section "Tutorial"
    Set-Civ6IniValue -IniPath $userOptions -Key "HasSeenXP2FeaturesScreen" -Value "1" -Section "Tutorial"
    Set-Civ6IniValue -IniPath $userOptions -Key "HideXP1FeaturesScreen" -Value "1" -Section "Tutorial"
    Set-Civ6IniValue -IniPath $userOptions -Key "HideXP2FeaturesScreen" -Value "1" -Section "Tutorial"
    Write-Host "Set windowed ${renderW}x${renderH} (menu sequence), low graphics, no intro movie, advisor disabled"
}
