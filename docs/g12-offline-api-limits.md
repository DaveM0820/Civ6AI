# Game 12 offline API limits (production / traders / great people)

Researched against Sukritact Civilization VI Modding Knowledge Base and CivFanatics threads. No live Civ session; no OpenRouter spend.

## Production (AI seats)

Documented **Script** `CityBuildQueue` writers:

| Method | Effect |
|---|---|
| `CreateBuilding` / `CreateDistrict` / `CreateIncomplete*` | **Grant or place** the item (instant / incomplete), not “set the queue to build over time” |
| `AddProgress` / `FinishProgress` | Advance or finish the **current** item |
| `RemoveBuilding` / `RemoveDistrict` | Remove |
| `CanProduce`, `CurrentlyBuilding`, `GetTurnsLeft`, `Has*` | Read |

Documented **UI-only** queue / current-hash reads: `GetAt`, `GetSize`, `GetCurrentProductionTypeHash`.

`CityManager.RequestOperation(BUILD, …)` is the production-panel write. It is **local-player only** and does not sync for another seat in multiplayer.

**Conclusion:** there is still **no verified multiplayer-safe Gameplay call that sets an AI city’s build queue**. Using `Create*` / `FinishProgress` / `InitUnit` as a stand-in would cheat production and is out of scope. Keep bias + clear-on-start + host fill prefer-pick; next live session should only **read** the new `probe|api|obj=BuildQueue|callable=` / `|read=` lines, then a controlled TEST_MODE write with a 2-PC checksum if a real enqueue method appears.

## Traders

CivFanatics reports trade-route create APIs as **UI-context** (Gameplay `GetTradeRoutes` / related often nil). Wiki lists `Game.GetTradeManager` in Script+UI, but **CreateTradeRoute is not documented** as a Script writer. Host `UnitManager.RequestOperation(MAKE_TRADE_ROUTE)` does not sync for AI seats.

**Conclusion:** keep fail-closed `trade_route_unavailable:no_gameplay_route`. Live probe only: existence of `CreateTradeRoute` / `CanCreateTradeRoute` on an AI seat without desync.

## Great Writer / great-person activate

Activation goes through UI `UnitManager.RequestCommand`. Gameplay has `Game.GetGreatPeople():GrantPerson` / `CreatePerson` (spawn, not activate). Retire via `UnitManager.Kill` remains available.

**Conclusion:** keep fail-closed `activate_unavailable:no_gameplay_activate` until a synced Gameplay activate is proven.

## Embark refusals

Engine `MoveUnit` can still refuse a legal-looking embark/disembark (`domain_embark` / `domain_disembark`) with full moves. A `ChangeMovesRemaining` top-up was removed as unproven and non-vanilla. Offline we only improved refusal **copy** (closed borders / stacking). Root cause still needs an in-engine path/stacking/ops probe next game.
