# Shared Civ5Ai paths and helpers for testbed launch scripts.

function Get-Civ5AiRepoRoot {
    param([string]$FromScriptRoot = $PSScriptRoot)
    Split-Path -Parent (Split-Path -Parent $FromScriptRoot)
}

function Write-Utf8NoBom {
    param([string]$Path, [string]$Content)
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($Path, $Content, $utf8)
}

function Get-Civ5AiKnownDocuments {
    $known = [Environment]::GetFolderPath('MyDocuments')
    if ($known) { return $known }
    return (Join-Path $env:USERPROFILE "Documents")
}

function Get-Civ5AiMyGamesRoots {
    $candidates = @(
        (Join-Path $env:USERPROFILE 'Documents\My Games\Sid Meier''s Civilization 5'),
        (Join-Path (Get-Civ5AiKnownDocuments) 'My Games\Sid Meier''s Civilization 5'),
        (Join-Path $env:USERPROFILE 'OneDrive\Documents\My Games\Sid Meier''s Civilization 5')
    )
    $roots = @()
    $seen = @{}
    foreach ($path in $candidates) {
        if (-not $path) { continue }
        $key = $path.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        if (Test-Path -LiteralPath $path) { $roots += $path }
    }
    $withGame = @()
    foreach ($path in $roots) {
        $hasConfig = Test-Path -LiteralPath (Join-Path $path 'config.ini')
        $hasLog = Test-Path -LiteralPath (Join-Path $path 'Logs\Lua.log')
        if ($hasConfig -or $hasLog) {
            $withGame += $path
        }
    }
    if ($withGame.Count -gt 0) {
        $local = @($withGame | Where-Object { $_ -notmatch '(?i)[/\\]OneDrive[/\\]' })
        if ($local.Count -gt 0) { return @($local) }
        return @($withGame)
    }
    if ($roots.Count -eq 0) {
        return @($candidates[0])
    }
    return @($roots)
}

function Get-Civ5AiMyGamesRoot {
    $roots = @(Get-Civ5AiMyGamesRoots)
    return $roots[0]
}

function Resolve-Civ5LuaLog {
    $best = $null
    $bestTime = [datetime]::MinValue
    foreach ($root in Get-Civ5AiMyGamesRoots) {
        $path = Join-Path $root "Logs\Lua.log"
        if (Test-Path -LiteralPath $path) {
            $mtime = (Get-Item -LiteralPath $path).LastWriteTime
            if ($mtime -gt $bestTime) {
                $bestTime = $mtime
                $best = $path
            }
        }
    }
    if ($best) { return $best }
    return Join-Path (Get-Civ5AiMyGamesRoot) "Logs\Lua.log"
}

function Get-Civ5AiPaths {
    $myGames = Get-Civ5AiMyGamesRoot
    # Join-Path splits on apostrophe in "Sid Meier's Civilization 5".
    $modRoot = [IO.Path]::Combine($myGames, "MODS", "Civ5Ai")
    return @{
        MyGames = $myGames
        ModsRoot = [IO.Path]::Combine($myGames, "MODS")
        Civ5AiModRoot = $modRoot
        Civ5AiRoot = [IO.Path]::Combine($modRoot, "runtime")
        ConfigIni = [IO.Path]::Combine($myGames, "config.ini")
        LuaLog = Resolve-Civ5LuaLog
    }
}

function Resolve-Civ5AiPython {
    if ($env:CIV5AI_PYTHON -and (Test-Path -LiteralPath $env:CIV5AI_PYTHON)) {
        return $env:CIV5AI_PYTHON
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    throw "python not found on PATH"
}

function Find-Civ5InstallRoot {
    if ($env:CIV5_INSTALL -and (Test-Path -LiteralPath $env:CIV5_INSTALL)) {
        return $env:CIV5_INSTALL
    }

    $suffix = 'Sid Meier''s Civilization V'
    $steamRoots = @(
        "C:\Program Files (x86)\Steam\steamapps\common",
        "C:\Program Files\Steam\steamapps\common",
        "D:\Steam\steamapps\common",
        "D:\SteamLibrary\steamapps\common",
        "E:\Steam\steamapps\common",
        "G:\SteamLibrary\steamapps\common"
    )
    foreach ($steamRoot in $steamRoots) {
        $candidate = Join-Path $steamRoot $suffix
        if (Test-Path -LiteralPath (Join-Path $candidate "CivilizationV.exe")) {
            return $candidate
        }
    }

    foreach ($drive in 67..90) {
        $letter = [char]$drive
        foreach ($libName in @('Steam\steamapps\common', 'SteamLibrary\steamapps\common')) {
            $steamCommon = ('{0}:\{1}' -f $letter, $libName)
            if (-not (Test-Path -LiteralPath $steamCommon)) { continue }
            $candidate = Join-Path $steamCommon $suffix
            if (Test-Path -LiteralPath (Join-Path $candidate "CivilizationV.exe")) {
                return $candidate
            }
        }
    }

    return $null
}

function Find-Civ5GameExe {
    $root = Find-Civ5InstallRoot
    if (-not $root) { return $null }
    $exe = Join-Path $root "CivilizationV.exe"
    if (Test-Path -LiteralPath $exe) { return $exe }
    return $null
}

function Stop-Civ5Processes {
    Get-Process -Name "CivilizationV" -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "Stopping CivilizationV pid $($_.Id)"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

function Test-Civ5ProcessRunning {
    return [bool](Get-Process -Name "CivilizationV" -ErrorAction SilentlyContinue)
}

function Wait-Civ5Process {
    param([int]$TimeoutSeconds = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Civ5ProcessRunning) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Set-Civ5IniValue {
    param(
        [string]$IniPath,
        [string]$Key,
        [string]$Value
    )
    if (-not (Test-Path -LiteralPath $IniPath)) {
        return $false
    }
    $backup = "$IniPath.civ5ai.bak"
    if (-not (Test-Path -LiteralPath $backup)) {
        Copy-Item -LiteralPath $IniPath -Destination $backup -Force
    }
    $lines = @(Get-Content -LiteralPath $IniPath -ErrorAction SilentlyContinue)
    $pattern = '^\s*' + [regex]::Escape($Key) + '\s*='
    $newLine = "$Key = $Value"
    $found = $false
    $out = @()
    foreach ($line in $lines) {
        if ($line -match $pattern) {
            $out += $newLine
            $found = $true
        } else {
            $out += $line
        }
    }
    if (-not $found) {
        $out += $newLine
    }
    Write-Utf8NoBom -Path $IniPath -Content (($out -join "`r`n") + "`r`n")
    return $true
}

function Write-Civ5AiWindowedGraphics {
    param(
        [string]$MyGamesRoot = "",
        [int]$WindowWidth = 1280,
        [int]$WindowHeight = 720
    )
    $roots = if ($MyGamesRoot) { @($MyGamesRoot) } else { Get-Civ5AiMyGamesRoots }
    foreach ($root in $roots) {
        foreach ($iniName in @("GraphicsSettingsDX11.ini", "GraphicsSettingsDX9.ini")) {
            $iniPath = Join-Path $root $iniName
            if (-not (Test-Path -LiteralPath $iniPath)) { continue }
            Set-Civ5IniValue -IniPath $iniPath -Key "FullScreen" -Value "0"
            Set-Civ5IniValue -IniPath $iniPath -Key "WindowResX" -Value "$WindowWidth"
            Set-Civ5IniValue -IniPath $iniPath -Key "WindowResY" -Value "$WindowHeight"
            Write-Host ('Windowed graphics: ' + $iniPath + ' (' + $WindowWidth + 'x' + $WindowHeight + ')')
        }
    }
}

function Ensure-Civ5ConfigIniKeys {
    param([string]$ConfigIniPath)

    if (-not (Test-Path -LiteralPath $ConfigIniPath)) {
        Write-Host ('config.ini not found at ' + $ConfigIniPath + ' - Civ5 may not have been launched yet.')
        return
    }

    $backup = "$ConfigIniPath.civ5ai.bak"
    if (-not (Test-Path -LiteralPath $backup)) {
        Copy-Item -LiteralPath $ConfigIniPath -Destination $backup -Force
        Write-Host ('Backed up config.ini to ' + $backup)
    }

    $lines = Get-Content -LiteralPath $ConfigIniPath
    $replacements = @{
        "EnableTuner" = "0"
        "LoggingEnabled" = "1"
        "MessageLog" = "1"
        "SkipIntroVideo" = "1"
        "LooseFilesOverridePAK" = "1"
    }
    $gameReplacements = @{
        "QuickCombat" = "1"
        "QuickMovement" = "1"
        "WorldSize" = "WORLDSIZE_DUEL"
        "GameSpeed" = "GAMESPEED_QUICK"
        "Map" = "Assets\Maps\Continents.lua"
        "QuickHandicap" = "HANDICAP_CHIEFTAIN"
    }

    $out = New-Object System.Collections.Generic.List[string]
    $inGame = $false
    $seen = @{}
    $seenGame = @{}

    foreach ($line in $lines) {
        $trim = $line.Trim()
        if ($trim -eq '[GAME]') {
            $inGame = $true
            $out.Add($line)
            continue
        }
        if ($trim.StartsWith("[") -and $trim.EndsWith("]") -and $trim -ne '[GAME]') {
            $inGame = $false
        }

        if (-not $inGame -and $trim -match '^([^=]+?)\s*=\s*(.*)$') {
            $key = $matches[1].Trim()
            if ($replacements.ContainsKey($key)) {
                $out.Add("$key = $($replacements[$key])")
                $seen[$key] = $true
                continue
            }
        }

        if ($inGame -and $trim -match '^([^=]+?)\s*=\s*(.*)$') {
            $key = $matches[1].Trim()
            if ($gameReplacements.ContainsKey($key)) {
                $out.Add("$key = $($gameReplacements[$key])")
                $seenGame[$key] = $true
                continue
            }
        }

        $out.Add($line)
    }

    foreach ($key in $replacements.Keys) {
        if (-not $seen.ContainsKey($key)) {
            $out.Add("$key = $($replacements[$key])")
        }
    }

    if (-not ($out -contains '[GAME]')) {
        $out.Add("")
        $out.Add('[GAME]')
    }
    foreach ($key in $gameReplacements.Keys) {
        if (-not $seenGame.ContainsKey($key)) {
            $out.Add("$key = $($gameReplacements[$key])")
        }
    }

    Write-Utf8NoBom -Path $ConfigIniPath -Content (($out -join "`r`n") + "`r`n")
    Write-Host ('Patched config.ini at ' + $ConfigIniPath)
}

function Install-Civ5AiModToMods {
    param(
        [string]$RepoRoot,
        [string]$ModsRoot
    )
    $source = Join-Path $RepoRoot "artifacts\Civ5Ai"
    $target = Join-Path $ModsRoot "Civ5Ai"
    Write-Host ('Syncing Civ5Ai mod to ' + $target)
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    Copy-Item -Recurse -Force (Join-Path $source "Lua") (Join-Path $target "Lua")
    Copy-Item -Force (Join-Path $source "Civ5Ai.modinfo") (Join-Path $target "Civ5Ai.modinfo")
    return $target
}

function Install-Civ5AiDlcPack {
    param(
        [string]$RepoRoot,
        [string]$Civ5Install
    )
    $sourcePack = Join-Path $RepoRoot "artifacts\Civ5Ai\dlc-pack\Z-CIV5AI"
    $targetPack = Join-Path $Civ5Install "Assets\DLC\Z-CIV5AI"
    Write-Host ('Deploying DLC pack to ' + $targetPack)
    if (Test-Path -LiteralPath $targetPack) {
        Remove-Item -LiteralPath $targetPack -Recurse -Force
    }
    Copy-Item -Recurse -Force $sourcePack $targetPack
    $brokenLoader = Join-Path $targetPack "UI\InGame.lua"
    if (Test-Path -LiteralPath $brokenLoader) {
        Remove-Item -LiteralPath $brokenLoader -Force
    }
    return $targetPack
}

function Install-Civ5AiSmokeHooks {
    param(
        [string]$RepoRoot,
        [string]$Civ5Install,
        [string]$IncludeLine = 'include( "Civ5Ai_InGame" );'
    )
    Install-Civ5AiInGameHooks -RepoRoot $RepoRoot -Civ5Install $Civ5Install -IncludeLine $IncludeLine
}

function Install-Civ5AiInGameHooks {
    param(
        [string]$RepoRoot,
        [string]$Civ5Install,
        [string]$MyGamesRoot = "",
        [string]$IncludeLine = 'include( "Civ5Ai_InGame" );'
    )
    $luaSourceDir = Join-Path $RepoRoot "artifacts\Civ5Ai\Lua"
    if ($MyGamesRoot) {
        $syncedLua = Join-Path (Join-Path $MyGamesRoot "MODS\Civ5Ai") "Lua"
        if (Test-Path -LiteralPath $syncedLua) {
            $luaSourceDir = $syncedLua
        }
    }
    if (-not (Test-Path -LiteralPath $luaSourceDir)) {
        throw "Missing Civ5Ai Lua at $luaSourceDir"
    }

    $inGameDir = Join-Path $Civ5Install "Assets\DLC\Expansion2\UI\InGame"
    $inGamePath = Join-Path $inGameDir "InGame.lua"
    if (-not (Test-Path -LiteralPath $inGamePath)) {
        $inGameDir = Join-Path $Civ5Install "Assets\UI\InGame"
        $inGamePath = Join-Path $inGameDir "InGame.lua"
    }
    if (-not (Test-Path -LiteralPath $inGamePath)) {
        throw "Could not find InGame.lua under Civ5 install"
    }

    $skipLua = @(
        'Civ5Ai_Smoke.lua',
        'Civ5Ai_FrontEnd.lua',
        'DiploCorner.lua',
        'Civ5Ai_PendingApply.lua',
        'Civ5Ai_ApplyPending.lua',
        'apply_pending.lua'
    )

    Get-ChildItem -LiteralPath $luaSourceDir -Filter "*.lua" | Where-Object {
        $skipLua -notcontains $_.Name
    } | ForEach-Object {
        $target = Join-Path $inGameDir $_.Name
        Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        Write-Host ('Copied ' + $_.Name + ' to ' + $target)
    }
    Get-ChildItem -LiteralPath $luaSourceDir -Filter "*.xml" | ForEach-Object {
        $target = Join-Path $inGameDir $_.Name
        Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        Write-Host ('Copied ' + $_.Name + ' to ' + $target)
    }
    $staleSmoke = Join-Path $inGameDir "Civ5Ai_Smoke.lua"
    if (Test-Path -LiteralPath $staleSmoke) {
        Remove-Item -LiteralPath $staleSmoke -Force
        Write-Host ('Removed stale ' + $staleSmoke)
    }
    $staleDiplo = Join-Path $inGameDir "DiploCorner.lua"
    if (Test-Path -LiteralPath $staleDiplo) {
        Remove-Item -LiteralPath $staleDiplo -Force
        Write-Host ('Removed stale ' + $staleDiplo)
    }
    foreach ($staleName in @('Civ5Ai_PendingApply.lua', 'Civ5Ai_ApplyPending.lua', 'apply_pending.lua')) {
        $stalePath = Join-Path $inGameDir $staleName
        if (Test-Path -LiteralPath $stalePath) {
            Remove-Item -LiteralPath $stalePath -Force
            Write-Host ('Removed stale ' + $stalePath)
        }
    }

    $text = Get-Content -LiteralPath $inGamePath -Raw
    if ($text -match 'Civ5Ai_InGame') {
        Write-Host ('InGame.lua already includes Civ5Ai_InGame: ' + $inGamePath)
    } else {
        $patched = $text.TrimEnd() + "`r`n`r`n-- Civ5Ai`r`n$IncludeLine`r`n"
        Write-Utf8NoBom -Path $inGamePath -Content $patched
        Write-Host ('Appended Civ5Ai_InGame include to ' + $inGamePath)
    }

    # Community Patch replaces Expansion2 InGame.lua. The DLC include never
    # runs while CP is enabled, so the same hook has to live in CP's file.
    $cpRoots = @()
    if ($MyGamesRoot) {
        $cpRoots += $MyGamesRoot
    }
    foreach ($root in Get-Civ5AiMyGamesRoots) {
        if ($cpRoots -notcontains $root) {
            $cpRoots += $root
        }
    }
    foreach ($root in $cpRoots) {
        $cpInGameDir = Join-Path $root "MODS\(1) Community Patch\Core Files\Overrides"
        $cpInGamePath = Join-Path $cpInGameDir "InGame.lua"
        if (-not (Test-Path -LiteralPath $cpInGamePath)) {
            continue
        }
        Get-ChildItem -LiteralPath $luaSourceDir -Filter "*.lua" | Where-Object {
            $skipLua -notcontains $_.Name
        } | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $cpInGameDir $_.Name) -Force
            Write-Host ('Copied ' + $_.Name + ' to ' + $cpInGameDir)
        }
        Get-ChildItem -LiteralPath $luaSourceDir -Filter "*.xml" | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $cpInGameDir $_.Name) -Force
            Write-Host ('Copied ' + $_.Name + ' to ' + $cpInGameDir)
        }
        foreach ($staleName in @('Civ5Ai_PendingApply.lua', 'Civ5Ai_ApplyPending.lua', 'apply_pending.lua')) {
            $staleCp = Join-Path $cpInGameDir $staleName
            if (Test-Path -LiteralPath $staleCp) {
                Remove-Item -LiteralPath $staleCp -Force
                Write-Host ('Removed stale ' + $staleCp)
            }
        }
        $cpText = Get-Content -LiteralPath $cpInGamePath -Raw
        if ($cpText -match 'Civ5Ai_InGame') {
            Write-Host ('CP InGame.lua already includes Civ5Ai_InGame: ' + $cpInGamePath)
        } else {
            $cpPatched = $cpText.TrimEnd() + "`r`n`r`n-- Civ5Ai`r`n$IncludeLine`r`n"
            Write-Utf8NoBom -Path $cpInGamePath -Content $cpPatched
            Write-Host ('Appended Civ5Ai_InGame include to ' + $cpInGamePath)
        }
    }
    $diploSource = Join-Path $luaSourceDir "DiploCorner.lua"
    $diploListSource = Join-Path $luaSourceDir "DiploList.lua"
    $tradeLogicSource = Join-Path $luaSourceDir "TradeLogic.lua"
    foreach ($root in $cpRoots) {
        $cpIncludesDir = Join-Path $root "MODS\(1) Community Patch\Core Files\Overrides\Includes"
        if ((Test-Path -LiteralPath $tradeLogicSource) -and (Test-Path -LiteralPath $cpIncludesDir)) {
            Copy-Item -LiteralPath $tradeLogicSource -Destination (Join-Path $cpIncludesDir "TradeLogic.lua") -Force
            Write-Host ('Copied TradeLogic.lua to ' + $cpIncludesDir)
        }
        $cpLuaDir = Join-Path $root "MODS\(1) Community Patch\LUA"
        if ((Test-Path -LiteralPath $diploSource) -and (Test-Path -LiteralPath $cpLuaDir)) {
            Copy-Item -LiteralPath $diploSource -Destination (Join-Path $cpLuaDir "DiploCorner.lua") -Force
            Write-Host ('Copied DiploCorner.lua to ' + $cpLuaDir)
        }
        if ((Test-Path -LiteralPath $diploListSource) -and (Test-Path -LiteralPath $cpLuaDir)) {
            Copy-Item -LiteralPath $diploListSource -Destination (Join-Path $cpLuaDir "DiploList.lua") -Force
            Write-Host ('Copied DiploList.lua to ' + $cpLuaDir)
        }
        $staleCpDiplo = Join-Path $root "MODS\(1) Community Patch\Core Files\Overrides\DiploCorner.lua"
        if (Test-Path -LiteralPath $staleCpDiplo) {
            Remove-Item -LiteralPath $staleCpDiplo -Force
            Write-Host ('Removed stale ' + $staleCpDiplo)
        }
    }
    return $inGamePath
}

function Install-Civ5AiFrontEndHooks {
    param(
        [string]$RepoRoot,
        [string]$Civ5Install
    )
    $frontEndDir = Join-Path $Civ5Install "Assets\UI\FrontEnd"
    $mainMenuPath = Join-Path $frontEndDir "MainMenu.lua"
    if (-not (Test-Path -LiteralPath $mainMenuPath)) {
        throw "Could not find MainMenu.lua under Civ5 install"
    }
    $source = Join-Path $RepoRoot "artifacts\Civ5Ai\Lua\Civ5Ai_FrontEnd.lua"
    $autostart = "Civ5Ai_Autostart = true`r`n"
    $luaInclude = "`r`n`r`n-- Civ5Ai`r`ninclude( `"Civ5Ai_FrontEnd`" );`r`n"
    function Add-Civ5AiLuaInclude([string]$LuaPath) {
        if (-not (Test-Path -LiteralPath $LuaPath)) {
            return
        }
        $existing = Get-Content -LiteralPath $LuaPath -Raw
        if ($existing -match 'Civ5Ai_FrontEnd') {
            Write-Host ('already includes Civ5Ai_FrontEnd: ' + $LuaPath)
            return
        }
        Write-Utf8NoBom -Path $LuaPath -Content ($existing.TrimEnd() + $luaInclude)
        Write-Host ('Appended Civ5Ai_FrontEnd include to ' + $LuaPath)
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $frontEndDir "Civ5Ai_FrontEnd.lua") -Force
    Write-Utf8NoBom -Path (Join-Path $frontEndDir "Civ5Ai_autostart.lua") -Content $autostart
    $moddingDir = Join-Path $frontEndDir "Modding"
    if (Test-Path -LiteralPath $moddingDir) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $moddingDir "Civ5Ai_FrontEnd.lua") -Force
        Write-Utf8NoBom -Path (Join-Path $moddingDir "Civ5Ai_autostart.lua") -Content $autostart
        Add-Civ5AiLuaInclude (Join-Path $moddingDir "InstalledPanel.lua")
        Add-Civ5AiLuaInclude (Join-Path $moddingDir "EULA.lua")
        Add-Civ5AiLuaInclude (Join-Path $moddingDir "ModsBrowser.lua")
        Add-Civ5AiLuaInclude (Join-Path $moddingDir "ModsMenu.lua")
        Add-Civ5AiLuaInclude (Join-Path $moddingDir "ModsSinglePlayer.lua")
    }
    $gameSetupDir = Join-Path $frontEndDir "GameSetup"
    if (Test-Path -LiteralPath $gameSetupDir) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $gameSetupDir "Civ5Ai_FrontEnd.lua") -Force
        Write-Utf8NoBom -Path (Join-Path $gameSetupDir "Civ5Ai_autostart.lua") -Content $autostart
        Add-Civ5AiLuaInclude (Join-Path $gameSetupDir "GameSetupScreen.lua")
    }
    Add-Civ5AiLuaInclude $mainMenuPath
    Add-Civ5AiLuaInclude (Join-Path $frontEndDir "LegalScreen.lua")
    Add-Civ5AiLuaInclude (Join-Path $frontEndDir "LoadScreen.lua")
    return $mainMenuPath
}

function Install-Civ5AutomationScript {
    param(
        [string]$RepoRoot,
        [string]$Civ5Install
    )
    $source = Join-Path $RepoRoot "scripts\testbed\civ5\RunCiv5AiAutoplay.lua"
    $automationDir = Join-Path $Civ5Install "Assets\Automation"
    $target = Join-Path $automationDir "RunCiv5AiAutoplay.lua"
    if (-not (Test-Path -LiteralPath $automationDir)) {
        New-Item -ItemType Directory -Force -Path $automationDir | Out-Null
    }
    Copy-Item -Force -LiteralPath $source -Destination $target
    Write-Host ('Copied Automation script to ' + $target)
    return $target
}

function New-Civ5AiSessionId {
    return ("autotest-" + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds())
}

function Ensure-Civ5AiSessionLayout {
    param(
        [string]$Civ5AiRoot,
        [string]$SessionId,
        [string]$ManagedSeats = "0"
    )
    $autotestDir = Join-Path $Civ5AiRoot "autotest"
    New-Item -ItemType Directory -Force -Path $autotestDir | Out-Null
    $seats = @()
    foreach ($token in ($ManagedSeats -split ',')) {
        $trimmed = $token.Trim()
        if ($trimmed -ne "") { $seats += $trimmed }
    }
    if ($seats.Count -eq 0) { $seats = @("0") }
    foreach ($seat in $seats) {
        $playerDir = Join-Path $Civ5AiRoot "sessions\$SessionId\PLAYER_$seat"
        New-Item -ItemType Directory -Force -Path $playerDir | Out-Null
    }
    $luaLog = Resolve-Civ5LuaLog
    if ($luaLog) {
        $logMirror = Join-Path (Split-Path -Parent $luaLog) "civ5ai"
        New-Item -ItemType Directory -Force -Path $logMirror | Out-Null
        foreach ($seat in $seats) {
            $playerDir = Join-Path $logMirror "sessions\$SessionId\PLAYER_$seat"
            New-Item -ItemType Directory -Force -Path $playerDir | Out-Null
        }
    }
}

function Write-Civ5AiAutotestEnv {
    param(
        [string]$Civ5AiRoot = "",
        [int]$StopTurn = 3,
        [string]$ManagedSeats = "0",
        [int]$SidecarLive = 0,
        [int]$FastEndTurn = 0,
        [string]$SessionId = ""
    )
    if ($SidecarLive -eq 1 -and $FastEndTurn -eq 1) {
        Write-Warning "CIV5AI_FAST_END_TURN=1 ignored while CIV5AI_SIDECAR_LIVE=1."
        $FastEndTurn = 0
    }
    $paths = Get-Civ5AiPaths
    if (-not $Civ5AiRoot) { $Civ5AiRoot = $paths.Civ5AiRoot }
    New-Item -ItemType Directory -Force -Path $Civ5AiRoot | Out-Null
    $lines = @(
        "CIV5AI_AUTOTEST=1",
        "CIV5AI_SIDECAR_LIVE=$SidecarLive",
        "CIV5AI_FAST_END_TURN=$FastEndTurn",
        "CIV5AI_MANAGED_SEATS=$ManagedSeats",
        "CIV5AI_AUTOTEST_STOP_TURN=$StopTurn"
    )
    if ($SessionId) { $lines += "CIV5AI_SESSION_ID=$SessionId" }
    $autotestEnv = Join-Path $Civ5AiRoot "autotest.env"
    Write-Utf8NoBom -Path $autotestEnv -Content (($lines -join "`r`n") + "`r`n")
    Write-Host ('Wrote ' + $autotestEnv)
}

function Remove-Civ5AiApplyPendingFile {
    param([string]$Civ5AiRoot = "")
    if (-not $Civ5AiRoot) {
        $Civ5AiRoot = (Get-Civ5AiPaths).Civ5AiRoot
    }
    $pending = Join-Path $Civ5AiRoot "apply_pending.lua"
    if (Test-Path -LiteralPath $pending) {
        Remove-Item -LiteralPath $pending -Force
        Write-Host ('Removed stale ' + $pending)
    }
}

function Write-Civ5AiRuntimeJson {
    param(
        [string]$Civ5AiRoot = "",
        [string]$SessionId = "",
        [string]$Python = "",
        [string]$Repo = "",
        [int]$SidecarLive = 1,
        [int]$SidecarTimeoutSeconds = 180
    )
    $paths = Get-Civ5AiPaths
    if (-not $Civ5AiRoot) { $Civ5AiRoot = $paths.Civ5AiRoot }
    if (-not $Python) { $Python = Resolve-Civ5AiPython }
    if (-not $Repo) { $Repo = Get-Civ5AiRepoRoot -FromScriptRoot $PSScriptRoot }
    New-Item -ItemType Directory -Force -Path $Civ5AiRoot | Out-Null
    Remove-Civ5AiApplyPendingFile -Civ5AiRoot $Civ5AiRoot
    $payload = @{
        session_id = $SessionId
        sidecar_live = $SidecarLive
        python = $Python
        repo = $Repo
        sidecar_timeout_seconds = $SidecarTimeoutSeconds
    } | ConvertTo-Json
    $runtimePath = Join-Path $Civ5AiRoot "runtime.json"
    Write-Utf8NoBom -Path $runtimePath -Content ($payload + "`r`n")
    Write-Host ('Wrote ' + $runtimePath)
}

function Sync-Civ5AiHostEnvKeys {
    param(
        [string]$Repo = "",
        [string]$Civ5AiRoot = ""
    )
    if (-not $Repo) { $Repo = Get-Civ5AiRepoRoot -FromScriptRoot $PSScriptRoot }
    $paths = Get-Civ5AiPaths
    if (-not $Civ5AiRoot) { $Civ5AiRoot = $paths.Civ5AiRoot }
    $repoEnv = Join-Path $Repo ".env"
    $hostEnv = Join-Path $Civ5AiRoot "host.env"
    New-Item -ItemType Directory -Force -Path $Civ5AiRoot | Out-Null
    $wanted = @("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "GEMINI_MODEL")
    $fromRepo = @{}
    if (Test-Path -LiteralPath $repoEnv) {
        Get-Content -LiteralPath $repoEnv | ForEach-Object {
            if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
            $name, $value = $_.Split('=', 2)
            $name = $name.Trim()
            $value = $value.Trim().Trim('"').Trim("'")
            if ($wanted -contains $name -and $value) {
                $fromRepo[$name] = $value
            }
        }
    }
    if ($fromRepo.Count -eq 0) {
        Write-Host "No API keys found in repo .env for host.env"
        return
    }
    $existing = @{}
    if (Test-Path -LiteralPath $hostEnv) {
        Get-Content -LiteralPath $hostEnv | ForEach-Object {
            if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
            $name, $value = $_.Split('=', 2)
            $existing[$name.Trim()] = $value
        }
    }
    $lines = @()
    if (Test-Path -LiteralPath $hostEnv) {
        $lines = @(Get-Content -LiteralPath $hostEnv)
    }
    $added = 0
    foreach ($name in $wanted) {
        if (-not $fromRepo.ContainsKey($name)) { continue }
        if ($existing.ContainsKey($name) -and $existing[$name] -and ($existing[$name] -notmatch 'your-key-here')) {
            continue
        }
        $lines += ($name + "=" + $fromRepo[$name])
        $added += 1
    }
    if ($added -gt 0) {
        Write-Utf8NoBom -Path $hostEnv -Content (($lines -join "`r`n") + "`r`n")
        Write-Host ("Updated host.env API keys (" + $added + " values). Path not logged with secrets.")
    } else {
        Write-Host "host.env already has API keys"
    }
}

function Assert-Civ5AiLiveSidecarReady {
    param(
        [string]$Civ5AiRoot = "",
        [string]$Civ5AiModRoot = ""
    )
    $paths = Get-Civ5AiPaths
    if (-not $Civ5AiRoot) { $Civ5AiRoot = $paths.Civ5AiRoot }
    if (-not $Civ5AiModRoot) { $Civ5AiModRoot = $paths.Civ5AiModRoot }

    $runtimePath = Join-Path $Civ5AiRoot "runtime.json"
    if (-not (Test-Path -LiteralPath $runtimePath)) {
        throw ("Live sidecar: runtime.json missing at " + $runtimePath)
    }
    $runtime = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
    $live = $runtime.sidecar_live
    if (-not ($live -eq 1 -or $live -eq $true -or [string]$live -eq "1")) {
        throw "Live sidecar: runtime.json sidecar_live is not 1"
    }

    $pathsLua = Join-Path $Civ5AiModRoot "Lua\Civ5Ai_Paths.lua"
    $luaReady = $false
    foreach ($attempt in 1..15) {
        if (Test-Path -LiteralPath $pathsLua) {
            $luaReady = $true
            break
        }
        Start-Sleep -Milliseconds 200
    }
    if (-not $luaReady) {
        throw ("Live sidecar: Civ5Ai_Paths.lua missing at " + $pathsLua)
    }
    $lua = Get-Content -LiteralPath $pathsLua -Raw
    if ($lua -notmatch 'SidecarLive\s*=\s*1') {
        throw "Live sidecar: Civ5Ai_Paths.lua SidecarLive is not 1"
    }

    $hostEnv = Join-Path $Civ5AiRoot "host.env"
    $hasKey = $false
    if (Test-Path -LiteralPath $hostEnv) {
        Get-Content -LiteralPath $hostEnv | ForEach-Object {
            if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
            $name, $value = $_.Split('=', 2)
            $name = $name.Trim()
            $value = $value.Trim().Trim('"').Trim("'")
            if ($name -in @("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY") -and $value -and $value -notmatch 'your-key-here') {
                $hasKey = $true
            }
        }
    }
    if (-not $hasKey) {
        throw "Live sidecar: host.env has no GEMINI_API_KEY, GOOGLE_API_KEY, or OPENAI_API_KEY"
    }
    Write-Host "Live sidecar ready: sidecar_live=1, Paths.lua SidecarLive=1, API key present. LLM chat.all and chat.LeaderName (met civs) apply on that civ's turn."
}
