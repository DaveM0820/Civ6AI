# Civ6Ai LAN unit-control probe (run only after SP probe passes)

Requires two running game copies (host + client) with identical Civ6Ai mod and managed AI seats.
Host runs the Python sidecar; client has no sidecar.

## Preconditions

- SP QuickLive shows `apply|probe|move|ok` or `apply|script_move|ok` in Lua.log
  (M0; flag **off** first to confirm SP regression)
- Both PCs: same mod version (`scripts/install_mod.py`)
- Host: `CIV6AI_MANAGED_SEATS` lists AI seats only; human occupies one seat
- For M2: **`CIV6AI_MP_MOVE_SYNC=1`** (or `MpMoveSync = 1` in `Civ6Ai_Paths.lua`) on **both** PCs

## Sync probe (before full soak)

On host, inject via hidden inbox (or public chat):

```text
CIV6AI|mp_sync_probe|<playerID>|<unitNumericId>|<x>|<y>
```

Expect on **both** PCs in Lua.log:

- `apply|mp_sync|probe|…`
- `apply|mp_sync|exec|ok|player=…|unit=…|plot=x,y`

Then confirm unit plot parity visually and no new OOS lines.

## Run (20 turns)

```powershell
# Host — enable M2 sync in Paths or GameConfiguration before launch
$env:CIV6AI_SIDECAR_LIVE = "1"
# After session, on BOTH PCs inspect OOSLog:
$oos = "$env:LOCALAPPDATA\Firaxis Games\Sid Meier's Civilization VI\Logs\OOSLog.log"
Select-String -Path $oos -Pattern "Out Of Sync" -SimpleMatch
```

(Use your usual QuickLive / sidecar launch scripts if present on the machine.)

## Pass criteria

- No new OOS lines after turn 1 on either PC
- Lua.log on host shows `bridge|inbox_apply_done` and `apply|ok|move_unit` for managed seats
- Host also shows `apply|mp_sync|enqueue` / `apply|mp_sync|exec|ok` when the flag is on
- Friend shows `apply|mp_sync|exec|ok` for the same seq/plot
- Units moved by LLM appear at the same plots on both clients

## Fail actions

- OOS on unit moves: capture both OOSLogs; see `docs/MP_SYNC_TRANSPORT.md` fallbacks
  (engine-synced ops or CE). Do not treat host-only Apply as success.
- Apply timeout only on host → verify hidden inbox inject (`inbox|apply_ready` in Lua.log)
- `local_player_swap_blocked_mp` → expected in MP without sync path; flag must be on
