-- Civ6Ai "build next": one engine AI strategy per buildable item. The model
-- names an item for its seat (set_build_next); gameplay Lua stores it in the
-- synced game property CIV6AI_PICK_<player> (an index into Civ6Ai_NextItems)
-- and GameEvents.Civ6AiNext_<Item>(playerID, threshold) answers true for that
-- seat's pick only. Two lists per strategy:
--  * a one-item Units/Buildings/Districts AiFavoredItems list (Favored=1). In
--    vanilla these systems only rank items *within* their category; Value is
--    largely ignored (vanilla uses Favored with Value 0/1).
--  * a PseudoYields list boosting the item's category (settler, trade, naval,
--    land/air combat, explorer, religious, archaeologist, spy, improvement for
--    builders, district) by +1500. The engine AI picks the category first by
--    pseudoyield. Our production presets (Civ6Ai_Priorities.sql) move a
--    category by -100 .. +1000 (SETTLERS_ONLY_ALL_IN settler +1000,
--    NAVAL_TOTAL_WAR_ALL_IN naval +880). +1500 keeps the picked category on top
--    even when the active preset cuts it by 100 and lifts a rival by 1000
--    (net +1400 vs +1000).
--    Buildings have no category pseudoyield in vanilla, so building picks
--    rely on the favoured list only.
-- The engine still chooses the city, costs, chops and overflow: vanilla rules.
-- Same 'Call Lua Function' pattern as Civ6Ai_Strategies.sql (FORCE_*).
-- Wonders are not listed (they need a plot). Projects are not listed either:
-- vanilla has no favoured-projects list system for the engine AI.

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

-- Category boost (see header). One PseudoYields list per item that has a
-- category pseudoyield: the unit's own Units.PseudoYieldType (vanilla sets it
-- for settler, builder, trader, religious, spy, archaeologist, ...), else its
-- formation (land/naval/air combat); districts -> PSEUDOYIELD_DISTRICT. Names
-- checked against vanilla Yields.xml/Units.xml, and the
-- JOIN on PseudoYields keeps the FK valid if a ruleset lacks one.
CREATE TABLE IF NOT EXISTS Civ6Ai_NextCategory (
  Item TEXT NOT NULL PRIMARY KEY,
  PseudoYield TEXT NOT NULL
);
INSERT OR IGNORE INTO Civ6Ai_NextCategory (Item, PseudoYield)
SELECT UnitType, COALESCE(PseudoYieldType, CASE
  WHEN FormationClass = 'FORMATION_CLASS_NAVAL' THEN 'PSEUDOYIELD_UNIT_NAVAL_COMBAT'
  WHEN FormationClass = 'FORMATION_CLASS_AIR' THEN 'PSEUDOYIELD_UNIT_AIR_COMBAT'
  WHEN FormationClass = 'FORMATION_CLASS_LAND_COMBAT' THEN 'PSEUDOYIELD_UNIT_COMBAT'
  END)
FROM Units WHERE UnitType IN (SELECT Item FROM Civ6Ai_NextItems WHERE System = 'Units')
  AND COALESCE(PseudoYieldType, CASE
  WHEN FormationClass IN ('FORMATION_CLASS_NAVAL', 'FORMATION_CLASS_AIR', 'FORMATION_CLASS_LAND_COMBAT') THEN 'x' END) IS NOT NULL;
INSERT OR IGNORE INTO Civ6Ai_NextCategory (Item, PseudoYield)
SELECT Item, 'PSEUDOYIELD_DISTRICT' FROM Civ6Ai_NextItems WHERE System = 'Districts';
DELETE FROM Civ6Ai_NextCategory WHERE PseudoYield NOT IN (SELECT PseudoYieldType FROM PseudoYields);

INSERT INTO AiListTypes (ListType)
SELECT 'Civ6AiNextPY_' || Item FROM Civ6Ai_NextCategory;

INSERT INTO AiLists (ListType, System)
SELECT 'Civ6AiNextPY_' || Item, 'PseudoYields' FROM Civ6Ai_NextCategory;

INSERT INTO Strategy_Priorities (StrategyType, ListType)
SELECT 'CIV6AI_NEXT_' || Item, 'Civ6AiNextPY_' || Item FROM Civ6Ai_NextCategory;

INSERT INTO AiFavoredItems (ListType, Item, Favored, Value)
SELECT 'Civ6AiNextPY_' || Item, PseudoYield, 1, 1500 FROM Civ6Ai_NextCategory;
