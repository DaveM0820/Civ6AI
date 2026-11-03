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
--    builders, district) by +300. PseudoYield values are percentages of the
--    category's base value (Infixo Real Strategy wiki, PseudoYields), so +300
--    is 4x; the old +1500 (16x) swamped every other weight.
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
SELECT 'Civ6AiNextPY_' || Item, PseudoYield, 1, 300 FROM Civ6Ai_NextCategory;

-- ---------------------------------------------------------------------------
-- Direct request (test: UNIT_SETTLER only). Scouting quotas and boost hunting
-- reach the city through the "Build Unit" behaviour-tree node, which skips
-- pseudoyield scoring. This adds a self-starting AI operation whose tree is
-- Expansion2's "Build Railroad" (Expansion2_AI.xml:60-108) without its move /
-- improve half and with UNIT_SETTLER named in "Find Available Unit" "Unit
-- Type" (as Railroad names UNIT_MILITARY_ENGINEER). Its operation type has a
-- base limit of 0; only the per-seat CIV6AI_NEXT_UNIT_SETTLER strategy (Lua
-- condition on the synced pick) raises it to 1 - the same mechanism as
-- vanilla VICTORY_STRATEGY_MILITARY_VICTORY -> MilitaryVictoryOperations
-- (Victories.xml:138,201,278). Seats with no pick (P5, humans) stay at 0.
-- UNVERIFIED: a new AiOperationTypes Value (7; vanilla has 0..6) and whether
-- the engine starts a SelfStart op for majors from Default_List.
-- GAME 10 (T1-28): no sign it ran - settler picks were still beaten by
-- builders/slingers/galleys for 4-9 turns. Static review: Build Railroad is
-- NOT an AiOperation; it is a TriggeredBehaviorTree (TRIGGER_RAILROAD,
-- AI_EVENT_NEEDS_RAILROAD, DefaultTriggeredTrees) started by an engine-raised
-- AI event, which Lua cannot raise. Every vanilla SelfStart op uses one of the
-- 7 engine OperationType values; a new Value 7 has no precedent and is most
-- likely ignored by the engine's fixed enum. No MP-safe fix found; harmless
-- as is (limit 0 unless a pick is active). Candidate for removal.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS Civ6Ai_DirectUnits (
  Item TEXT NOT NULL PRIMARY KEY,
  OpValue INTEGER NOT NULL
);
INSERT OR IGNORE INTO Civ6Ai_DirectUnits (Item, OpValue)
SELECT Item, 7 FROM Civ6Ai_NextItems WHERE Item = 'UNIT_SETTLER';

INSERT INTO AiOperationTypes (OperationType, Value)
SELECT 'CIV6AI_OP_NEXT_' || Item, OpValue FROM Civ6Ai_DirectUnits;

INSERT INTO AiFavoredItems (ListType, Item, Value)
SELECT 'BaseOperationsLimits', 'CIV6AI_OP_NEXT_' || Item, 0 FROM Civ6Ai_DirectUnits;

INSERT INTO BehaviorTrees (TreeName)
SELECT 'Civ6Ai Next ' || Item FROM Civ6Ai_DirectUnits;

-- 0 Sequence -> 1 Decode Trigger, 2 Priority(3 Find Available Unit,
-- 4 Contract Manager Decorator -> 5 Build Unit). JumpTo = first node after the
-- subtree (6 = end).
INSERT INTO BehaviorTreeNodes (TreeName, NodeId, JumpTo, NodeType)
SELECT 'Civ6Ai Next ' || d.Item, n.NodeId, n.JumpTo, n.NodeType FROM Civ6Ai_DirectUnits d,
(SELECT 0 AS NodeId, 6 AS JumpTo, 'Sequence' AS NodeType
 UNION ALL SELECT 1, 0, 'Decode Trigger'
 UNION ALL SELECT 2, 6, 'Priority'
 UNION ALL SELECT 3, 0, 'Find Available Unit'
 UNION ALL SELECT 4, 6, 'Contract Manager Decorator'
 UNION ALL SELECT 5, 0, 'Build Unit') n;

-- TreeData mirrors Build Railroad nodes 1,3,4,5 (Railroad's trigger tag is
-- dropped). Build Unit: Required City -1 (any), Release Unit When Built 1 (as Build Trigger Unit).
INSERT INTO TreeData (DefnId, NodeId, TreeName, Tag, DefaultData)
SELECT t.DefnId, t.NodeId, 'Civ6Ai Next ' || d.Item, t.Tag,
  CASE WHEN t.DefaultData = '@ITEM' THEN d.Item ELSE t.DefaultData END
FROM Civ6Ai_DirectUnits d,
(SELECT 0 AS DefnId, 1 AS NodeId, NULL AS Tag, NULL AS DefaultData
 UNION ALL SELECT 1, 1, NULL, NULL UNION ALL SELECT 2, 1, NULL, NULL UNION ALL SELECT 3, 1, NULL, NULL
 UNION ALL SELECT 4, 1, NULL, NULL UNION ALL SELECT 5, 1, NULL, NULL UNION ALL SELECT 6, 1, NULL, NULL
 UNION ALL SELECT 7, 1, NULL, NULL UNION ALL SELECT 8, 1, 'Next Value', NULL
 UNION ALL SELECT 0, 3, 'Next Units', NULL
 UNION ALL SELECT 2, 3, 'Next Unit', NULL
 UNION ALL SELECT 3, 3, NULL, NULL
 UNION ALL SELECT 4, 3, NULL, '@ITEM'
 UNION ALL SELECT 0, 4, 'Next Contract', NULL
 UNION ALL SELECT 1, 4, NULL, NULL
 UNION ALL SELECT 2, 4, NULL, '5'
 UNION ALL SELECT 0, 5, 'Next Units', NULL
 UNION ALL SELECT 1, 5, NULL, NULL
 UNION ALL SELECT 2, 5, NULL, '-1'
 UNION ALL SELECT 3, 5, NULL, '1'
 UNION ALL SELECT 4, 5, 'Next Contract', NULL
 UNION ALL SELECT 6, 5, NULL, NULL
 UNION ALL SELECT 8, 5, 'Next Value', NULL) t;

INSERT INTO AiOperationDefs (OperationName, TargetType, TargetParameter, BehaviorTree, Priority,
  MaxTargetDistInRegion, MaxTargetDistInArea, MaxTargetDistInWorld, SelfStart, OperationType)
SELECT 'Civ6Ai Next ' || Item, 'TARGET_FRIENDLY_CITY', 0, 'Civ6Ai Next ' || Item, 4,
  -1, -1, 0, 1, 'CIV6AI_OP_NEXT_' || Item FROM Civ6Ai_DirectUnits;

INSERT INTO AiTeams (TeamName)
SELECT 'Civ6Ai Next Team ' || Item FROM Civ6Ai_DirectUnits;
INSERT INTO AiOperationTeams (TeamName, OperationName, MinUnits, InitialStrengthAdvantage, OngoingStrengthAdvantage)
SELECT 'Civ6Ai Next Team ' || Item, 'Civ6Ai Next ' || Item, 0, 0, 0 FROM Civ6Ai_DirectUnits;
-- Needs no units to start; takes no combat units.
INSERT INTO OpTeamRequirements (TeamName, AiType, MinNumber, MaxNumber)
SELECT 'Civ6Ai Next Team ' || Item, 'UNITAI_COMBAT', 0, 0 FROM Civ6Ai_DirectUnits;

INSERT INTO AllowedOperations (ListType, OperationDef)
SELECT 'Default_List', 'Civ6Ai Next ' || Item FROM Civ6Ai_DirectUnits;

INSERT INTO AiListTypes (ListType)
SELECT 'Civ6AiNextOp_' || Item FROM Civ6Ai_DirectUnits;
INSERT INTO AiLists (ListType, System)
SELECT 'Civ6AiNextOp_' || Item, 'AiOperationTypes' FROM Civ6Ai_DirectUnits;
INSERT INTO AiFavoredItems (ListType, Item, Value)
SELECT 'Civ6AiNextOp_' || Item, 'CIV6AI_OP_NEXT_' || Item, 1 FROM Civ6Ai_DirectUnits;
INSERT INTO Strategy_Priorities (StrategyType, ListType)
SELECT 'CIV6AI_NEXT_' || Item, 'Civ6AiNextOp_' || Item FROM Civ6Ai_DirectUnits;

-- ---------------------------------------------------------------------------
-- While a pick is active, make it the only attractive category: -100 (percent,
-- so ~zero) on every OTHER unit category, districts and wonders. Never
-- touches PSEUDOYIELD_CITY_DEFENSES / standing army / the City Defense tree.
-- Items with no category of their own (builder, buildings) cut all of them.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS Civ6Ai_NextCutCategories (PseudoYield TEXT NOT NULL PRIMARY KEY);
INSERT OR IGNORE INTO Civ6Ai_NextCutCategories (PseudoYield)
SELECT PseudoYieldType FROM PseudoYields
WHERE PseudoYieldType LIKE 'PSEUDOYIELD_UNIT_%' OR PseudoYieldType IN ('PSEUDOYIELD_DISTRICT', 'PSEUDOYIELD_WONDER');

INSERT INTO AiListTypes (ListType)
SELECT 'Civ6AiNextCut_' || Item FROM Civ6Ai_NextItems;
INSERT INTO AiLists (ListType, System)
SELECT 'Civ6AiNextCut_' || Item, 'PseudoYields' FROM Civ6Ai_NextItems;
INSERT INTO Strategy_Priorities (StrategyType, ListType)
SELECT 'CIV6AI_NEXT_' || Item, 'Civ6AiNextCut_' || Item FROM Civ6Ai_NextItems;
INSERT INTO AiFavoredItems (ListType, Item, Value)
SELECT 'Civ6AiNextCut_' || n.Item, c.PseudoYield, -100 FROM Civ6Ai_NextItems n, Civ6Ai_NextCutCategories c
WHERE c.PseudoYield <> COALESCE((SELECT PseudoYield FROM Civ6Ai_NextCategory k WHERE k.Item = n.Item), '');

-- Promotion classes: recon -100 unless the pick is recon; a unit pick with a
-- promotion class gets +100 on its own class.
INSERT INTO AiListTypes (ListType)
SELECT 'Civ6AiNextPC_' || Item FROM Civ6Ai_NextItems;
INSERT INTO AiLists (ListType, System)
SELECT 'Civ6AiNextPC_' || Item, 'UnitPromotionClasses' FROM Civ6Ai_NextItems;
INSERT INTO Strategy_Priorities (StrategyType, ListType)
SELECT 'CIV6AI_NEXT_' || Item, 'Civ6AiNextPC_' || Item FROM Civ6Ai_NextItems;
INSERT INTO AiFavoredItems (ListType, Item, Value)
SELECT 'Civ6AiNextPC_' || n.Item, 'PROMOTION_CLASS_RECON', -100 FROM Civ6Ai_NextItems n
WHERE EXISTS (SELECT 1 FROM UnitPromotionClasses WHERE PromotionClassType = 'PROMOTION_CLASS_RECON')
  AND n.Item NOT IN (SELECT UnitType FROM Units WHERE PromotionClass = 'PROMOTION_CLASS_RECON');
INSERT OR IGNORE INTO AiFavoredItems (ListType, Item, Value)
SELECT 'Civ6AiNextPC_' || u.UnitType, u.PromotionClass, 100 FROM Units u
WHERE u.UnitType IN (SELECT Item FROM Civ6Ai_NextItems) AND u.PromotionClass IS NOT NULL
  AND u.PromotionClass IN (SELECT PromotionClassType FROM UnitPromotionClasses);

-- ---------------------------------------------------------------------------
-- Model seats: land scout quota cut (vanilla DefaultScoutUse, Leaders.xml:
-- 809-813: 100/100/50 percent; STRATEGY_EARLY_EXPLORATION adds +200 to
-- DEFAULT_LAND_SCOUTS while the seat has few cities, so that one is -300). Naval scouting kept (islands). Gated by
-- GameEvents.Civ6AiModelSeat: an AI major the model has steered (a priority
-- preset or a build-next pick in synced properties). P5 / humans: off.
-- ---------------------------------------------------------------------------
INSERT INTO Types (Type, Kind) VALUES ('CIV6AI_MODEL_SEAT', 'KIND_VICTORY_STRATEGY');
INSERT INTO Strategies (StrategyType, VictoryType, NumConditionsNeeded) VALUES ('CIV6AI_MODEL_SEAT', NULL, 1);
INSERT INTO StrategyConditions (StrategyType, ConditionFunction, Disqualifier) VALUES ('CIV6AI_MODEL_SEAT', 'Is Not Major', 1);
INSERT INTO StrategyConditions (StrategyType, ConditionFunction, StringValue, ThresholdValue)
VALUES ('CIV6AI_MODEL_SEAT', 'Call Lua Function', 'Civ6AiModelSeat', 0);
INSERT INTO AiListTypes (ListType) VALUES ('Civ6AiModelScouts');
INSERT INTO AiLists (ListType, System) VALUES ('Civ6AiModelScouts', 'AiScoutUses');
INSERT INTO Strategy_Priorities (StrategyType, ListType) VALUES ('CIV6AI_MODEL_SEAT', 'Civ6AiModelScouts');
INSERT INTO AiFavoredItems (ListType, Item, Value)
SELECT 'Civ6AiModelScouts', ScoutUseType, CASE WHEN ScoutUseType = 'DEFAULT_LAND_SCOUTS' THEN -300 ELSE -100 END FROM AiScoutUses
WHERE ScoutUseType IN ('DEFAULT_LAND_SCOUTS', 'LAND_SCOUTS_PER_PRIMARY_REGION', 'LAND_SCOUTS_PER_SECONDARY_REGION');
