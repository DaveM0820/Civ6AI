-- Civ6Ai "build next": one engine AI strategy per buildable item. The model
-- names an item for its seat (set_build_next); gameplay Lua stores it in the
-- synced game property CIV6AI_PICK_<player> (an index into Civ6Ai_NextItems)
-- and GameEvents.Civ6AiNext_<Item>(playerID, threshold) answers true for that
-- seat's pick only. The strategy's one-item AiFavoredItems list (Value 1000)
-- makes the engine AI start that item at the next empty queue, with its own
-- city choice, costs, modifiers, chops and overflow: vanilla rules. Same
-- 'Call Lua Function' pattern as Civ6Ai_Strategies.sql (FORCE_*).
-- Projects and wonders are not listed (wonders need a plot; projects have no
-- engine AI list system).

CREATE TABLE IF NOT EXISTS Civ6Ai_NextItems (
  Item TEXT NOT NULL PRIMARY KEY,
  System TEXT NOT NULL
);

INSERT OR IGNORE INTO Civ6Ai_NextItems (Item, System)
SELECT UnitType, 'Units' FROM Units WHERE Cost > 0 ORDER BY UnitType;
INSERT OR IGNORE INTO Civ6Ai_NextItems (Item, System)
SELECT BuildingType, 'Buildings' FROM Buildings WHERE Cost > 0 AND IsWonder = 0 ORDER BY BuildingType;
INSERT OR IGNORE INTO Civ6Ai_NextItems (Item, System)
SELECT DistrictType, 'Districts' FROM Districts WHERE Cost > 0 AND DistrictType <> 'DISTRICT_CITY_CENTER' ORDER BY DistrictType;

INSERT INTO Types (Type, Kind)
SELECT 'CIV6AI_NEXT_' || Item, 'KIND_VICTORY_STRATEGY' FROM Civ6Ai_NextItems;

INSERT INTO Strategies (StrategyType, VictoryType, NumConditionsNeeded)
SELECT 'CIV6AI_NEXT_' || Item, NULL, 1 FROM Civ6Ai_NextItems;

INSERT INTO StrategyConditions (StrategyType, ConditionFunction, Disqualifier)
SELECT 'CIV6AI_NEXT_' || Item, 'Is Not Major', 1 FROM Civ6Ai_NextItems;

INSERT INTO StrategyConditions (StrategyType, ConditionFunction, StringValue, ThresholdValue)
SELECT 'CIV6AI_NEXT_' || Item, 'Call Lua Function', 'Civ6AiNext_' || Item, 0 FROM Civ6Ai_NextItems;

INSERT INTO AiListTypes (ListType)
SELECT 'Civ6AiNext_' || Item FROM Civ6Ai_NextItems;

INSERT INTO AiLists (ListType, System)
SELECT 'Civ6AiNext_' || Item, System FROM Civ6Ai_NextItems;

INSERT INTO Strategy_Priorities (StrategyType, ListType)
SELECT 'CIV6AI_NEXT_' || Item, 'Civ6AiNext_' || Item FROM Civ6Ai_NextItems;

INSERT INTO AiFavoredItems (ListType, Item, Favored, Value)
SELECT 'Civ6AiNext_' || Item, Item, 1, 1000 FROM Civ6Ai_NextItems;
