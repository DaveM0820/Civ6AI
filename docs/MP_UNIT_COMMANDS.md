# MP unit commands (Civ6 LLM AI)

## Problem

The blocker for live LAN multiplayer with LLM-driven units is **MP unit commands**.
Single-player Apply works (probe / script_move / move ok in Lua.log). In MP, host-local
Apply that relies on swapping the local player context does **not** safely drive remote
AI seats for every client.

Key marker from the Apply ladder: `local_player_swap_blocked_mp` — when the session is
network multiplayer, local-player swap is blocked and unit ops must not be applied as if
they were a single local human client.

## Apply ladder (SP → MP)

1. **SP probe** — QuickLive shows `apply|probe|move|ok` or `apply|script_move|ok` in Lua.log.
2. **Host inbox Apply** — sidecar injects pending Apply; host Lua shows `inbox|apply_ready`
   then `bridge|inbox_apply_done` / `apply|ok|move_unit` for managed seats.
3. **MP gate** — if `local_player_swap_blocked_mp` (or equivalent), do **not** pretend SP
   swap worked; require an all-client path.
4. **All-client sync** — every client must observe the same unit plot after the op
   (lan_probe pass: units moved by LLM at the same plots on both clients; no new OOS
   after turn 1).

## Why all-client sync

Civ6 MP simulation is authoritative across clients. A host-only mutation that does not
go through a GameCore-replicated unit command produces **Out Of Sync** (OOSLog
`Out Of Sync`). Friend's client must apply the same move, not merely render a host-side
side effect.

## LAN probe criteria (from `civ6_lan_probe.md`)

Preconditions: SP probe passes; identical Civ6Ai mod on both PCs; host sidecar with
`CIV6AI_MANAGED_SEATS` = AI seats only; human occupies one seat.

Pass:

- No new OOS lines after turn 1 on either PC
- Host Lua.log: `bridge|inbox_apply_done` and `apply|ok|move_unit` for managed seats
- Units moved by LLM at the **same plots** on both clients

Fail actions (evidence-driven):

- OOS on unit moves → plan CE fork **or** all-client GameCore `MoveUnit` broadcast
  (`EXECUTE_SCRIPT` path)
- Apply timeout only on host → verify hidden inbox inject (`inbox|apply_ready`)

## Recommended transport

See **`docs/MP_SYNC_TRANSPORT.md`** for the full option matrix and evidence levels.

**M2 primary (flagged, untested in-game):** all-client GameCore `MoveUnitForPlayer`,
with intent broadcast via `Network.SendChat` / `Events.MultiplayerChat`
(`CIV6AI_MP_MOVE_SYNC=1`). Module: `Civ6Ai_MpSync.lua`.

**Not assumed:** a stock `EXECUTE_SCRIPT` broadcast API — named in earlier notes but
**not present** in seed Lua. Revisit only with LAN evidence.

**Fallback:** CE fork / custom engine path if OOS persists; or host-only Apply with
forced resync (not preferred for LAN soak).

SP Apply remains the development ladder step; it is **not** the LAN MP solution.

## Evidence excerpts (seed-time)

### Civ6Ai_Apply.lua matches

- `L4: function Civ6Ai_Apply._IsNetworkMultiplayer()`
- `L5: if GameConfiguration ~= nil and GameConfiguration.IsNetworkMultiplayer ~= nil then`
- `L6: return GameConfiguration.IsNetworkMultiplayer()`
- `L65: if skipOp ~= nil and UnitManager.RequestOperation(unit, skipOp.Hash) then`
- `L70: if UnitManager.RequestOperation(unit, UnitOperationTypes.SKIP_TURN) then`
- `L74: if UnitManager ~= nil and UnitManager.FinishMoves ~= nil then`
- `L75: UnitManager.FinishMoves(unit)`
- `L82: if Civ6Ai_Apply._IsNetworkMultiplayer() then`
- `L83: return false, "local_player_swap_blocked_mp"`
- `L140: function Civ6Ai_Apply._MoveUnitGameCore(playerID, unitNumericId, x, y)`
- `L141: if ExposedMembers == nil or ExposedMembers.Civ6Ai == nil or ExposedMembers.Civ6Ai.MoveUnitForPlayer == nil then`
- `L142: return false, "gamecore_unavailable"`
- `L144: local ok, reason = ExposedMembers.Civ6Ai.MoveUnitForPlayer(playerID, unitNumericId, x, y)`
- `L147: "apply|script_move|ok|player="`
- `L159: "apply|script_move|fail|player="`
- `L164: return false, reason or "script_move_rejected"`
- `L167: function Civ6Ai_Apply._ResolveUnitsGameCore(playerID)`
- `L181: if not Civ6Ai_Apply._IsNetworkMultiplayer()`
- `L207: local gcOk, gcCount = Civ6Ai_Apply._ResolveUnitsGameCore(playerID)`
- `L210: "apply|resolve_units|player=" .. tostring(playerID) .. "|ok=true|gamecore_resolved=" .. tostring(gcCount)`
- `L230: return Civ6Ai_Apply._MoveUnit(playerID, args)`
- `L279: Civ6Ai_Util.Log("apply|research|gamecore|player=" .. tostring(playerID) .. "|tech=" .. tostring(techId))`
- `L321: if UnitManager.CanStartOperation == nil then`
- `L325: if UnitManager.CanStartOperation(unit, op, plot, true) then`
- `L330: if UnitManager.CanStartOperation(unit, op, nil, params, false) then`
- `L334: return UnitManager.CanStartOperation(unit, op, nil, true)`
- `L348: if UnitManager.RequestOperation ~= nil then`
- `L349: if plot ~= nil and UnitManager.RequestOperation(unit, op, plot) then`
- `L355: if UnitManager.RequestOperation(unit, op, params) then`
- `L361: if UnitManager.RequestOperation(unit, op) then`
- `L374: function Civ6Ai_Apply._MoveUnit(playerID, args)`
- `L400: local scriptOk, scriptReason = Civ6Ai_Apply._MoveUnitGameCore(playerID, numericId, x, y)`
- `L406: if not Civ6Ai_Apply._IsNetworkMultiplayer() then`
- `L481: if not Civ6Ai_Apply._IsNetworkMultiplayer() then`
- `L503: Civ6Ai_Util.Log("apply|found_city|gamecore|player=" .. tostring(playerID))`
- `L542: if not Civ6Ai_Apply._IsNetworkMultiplayer() then`
- `L568: if UnitManager.RequestOperation(unit, UnitOperationTypes.FORTIFY) then`
- `L572: UnitManager.FinishMoves(unit)`

### sidecar notes

- `civ6_wire.py:L24: "choose_dedication": ("legal.dedication", "dedication_index"),`
- `civ6_wire.py:L25: "choose_pantheon": ("legal.pantheon", "belief_id"),`
- `civ6_wire.py:L373: "temper (grandeur, austerity, wit, menace, piety, melancholy, etc.). "`
- `civ6_adapter.py:L373: "domain_id": "DOMAIN_LAND",`
- `civ6_adapter.py:L554: "network_multiplayer": False,`
- `civ6_adapter.py:L617: "land": None,`

### lan_probe (copied to docs/)

See `docs/civ6_lan_probe.md` for the full probe runbook.

## Workstream note

This repo (`civ6-llm-ai`) is separate from `civ5-llm-ai` and `civ4ai`. MP sync of unit
commands for David + friend on LAN is the primary goal; SP Apply already exists as the
foundation.
