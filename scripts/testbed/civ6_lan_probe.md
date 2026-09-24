# Civ6Ai LAN unit-control probe (run only after SP probe passes)

Requires two running game copies (host + client) with identical Civ6Ai mod and managed AI seats.
Host runs the Python sidecar; client has no sidecar.

## Preconditions

- SP QuickLive shows `apply|probe|move|ok` or `apply|script_move|ok` in Lua.log
- Both PCs: same mod version synced via `Invoke-Civ6AiModSync.ps1`
- Host: `CIV6AI_MANAGED_SEATS` lists AI seats only; human occupies one seat

## Run (20 turns)

```powershell
# Host
$env:CIV6AI_SIDECAR_LIVE = "1"
.\scripts\testbed\Invoke-Civ6AiSyncAndTest.ps1 -QuickLive -SidecarLive -ManagedSeats "1,2,3"

# After session, on BOTH PCs inspect OOSLog:
$oos = "$env:LOCALAPPDATA\Firaxis Games\Sid Meier's Civilization VI\Logs\OOSLog.log"
Select-String -Path $oos -Pattern "Out Of Sync" -SimpleMatch
```

## Pass criteria

- No new OOS lines after turn 1 on either PC
- Lua.log on host shows `bridge|inbox_apply_done` and `apply|ok|move_unit` for managed seats
- Units moved by LLM appear at the same plots on both clients

## Fail actions

- OOS on unit moves: plan CE fork or all-client GameCore `MoveUnit` broadcast (EXECUTE_SCRIPT path)
- Apply timeout only on host: verify hidden inbox inject (`inbox|apply_ready` in Lua.log)
