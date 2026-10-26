-- Civ6Ai build strategies: engine AI strategies that the model switches on.
-- Each strategy's condition is 'Call Lua Function': before every player's
-- turn the engine calls GameEvents.<StringValue>(playerID, threshold) in
-- gameplay Lua (Gameplay/Civ6Ai_Orders.lua), which answers from synced game
-- properties set through the order channel. When active, the strategy's
-- one-item AiFavoredItems list adds a large weight to that exact item in the
-- engine AI's own build choice. Same tables and pattern as Infixo's Real
-- Strategy (whose largest build weights are around 100).

INSERT INTO Types (Type, Kind) VALUES
('CIV6AI_STRATEGY_FORCE_ARCHER',  'KIND_VICTORY_STRATEGY'),
('CIV6AI_STRATEGY_FORCE_GRANARY', 'KIND_VICTORY_STRATEGY'),
('CIV6AI_STRATEGY_FORCE_CAMPUS',  'KIND_VICTORY_STRATEGY');

INSERT INTO Strategies (StrategyType, VictoryType, NumConditionsNeeded) VALUES
('CIV6AI_STRATEGY_FORCE_ARCHER',  NULL, 1),
('CIV6AI_STRATEGY_FORCE_GRANARY', NULL, 1),
('CIV6AI_STRATEGY_FORCE_CAMPUS',  NULL, 1);

INSERT INTO StrategyConditions (StrategyType, ConditionFunction, Disqualifier) VALUES
('CIV6AI_STRATEGY_FORCE_ARCHER',  'Is Not Major', 1),
('CIV6AI_STRATEGY_FORCE_GRANARY', 'Is Not Major', 1),
('CIV6AI_STRATEGY_FORCE_CAMPUS',  'Is Not Major', 1);

INSERT INTO StrategyConditions (StrategyType, ConditionFunction, StringValue, ThresholdValue) VALUES
('CIV6AI_STRATEGY_FORCE_ARCHER',  'Call Lua Function', 'Civ6AiForceArcher',  0),
('CIV6AI_STRATEGY_FORCE_GRANARY', 'Call Lua Function', 'Civ6AiForceGranary', 0),
('CIV6AI_STRATEGY_FORCE_CAMPUS',  'Call Lua Function', 'Civ6AiForceCampus',  0);

INSERT INTO AiListTypes (ListType) VALUES
('Civ6AiForceArcherUnits'),
('Civ6AiForceGranaryBuildings'),
('Civ6AiForceCampusDistricts');

INSERT INTO AiLists (ListType, System) VALUES
('Civ6AiForceArcherUnits',      'Units'),
('Civ6AiForceGranaryBuildings', 'Buildings'),
('Civ6AiForceCampusDistricts',  'Districts');

INSERT INTO Strategy_Priorities (StrategyType, ListType) VALUES
('CIV6AI_STRATEGY_FORCE_ARCHER',  'Civ6AiForceArcherUnits'),
('CIV6AI_STRATEGY_FORCE_GRANARY', 'Civ6AiForceGranaryBuildings'),
('CIV6AI_STRATEGY_FORCE_CAMPUS',  'Civ6AiForceCampusDistricts');

INSERT INTO AiFavoredItems (ListType, Item, Favored, Value) VALUES
('Civ6AiForceArcherUnits',      'UNIT_ARCHER',      1, 1000),
('Civ6AiForceGranaryBuildings', 'BUILDING_GRANARY', 1, 1000),
('Civ6AiForceCampusDistricts',  'DISTRICT_CAMPUS',  1, 1000);

-- Early-game mode markers (expand / threat) for a seat the model drives with
-- fewer than 3 cities by turn 60. They carry no build weights any more: what
-- gets built follows the model's production preset. Kept for the early_mode
-- log. Exclusive.
INSERT INTO Types (Type, Kind) VALUES
('CIV6AI_STRATEGY_EARLY_EXPAND', 'KIND_VICTORY_STRATEGY'),
('CIV6AI_STRATEGY_EARLY_THREAT', 'KIND_VICTORY_STRATEGY');

INSERT INTO Strategies (StrategyType, VictoryType, NumConditionsNeeded) VALUES
('CIV6AI_STRATEGY_EARLY_EXPAND', NULL, 1),
('CIV6AI_STRATEGY_EARLY_THREAT', NULL, 1);

INSERT INTO StrategyConditions (StrategyType, ConditionFunction, Disqualifier) VALUES
('CIV6AI_STRATEGY_EARLY_EXPAND', 'Is Not Major', 1),
('CIV6AI_STRATEGY_EARLY_THREAT', 'Is Not Major', 1);

INSERT INTO StrategyConditions (StrategyType, ConditionFunction, StringValue, ThresholdValue) VALUES
('CIV6AI_STRATEGY_EARLY_EXPAND', 'Call Lua Function', 'Civ6AiEarlyExpand', 0),
('CIV6AI_STRATEGY_EARLY_THREAT', 'Call Lua Function', 'Civ6AiEarlyThreat', 0);

INSERT INTO AiListTypes (ListType) VALUES
('Civ6AiEarlyExpandPseudoYields'),
('Civ6AiEarlyThreatPseudoYields');

INSERT INTO AiLists (ListType, System) VALUES
('Civ6AiEarlyExpandPseudoYields', 'PseudoYields'),
('Civ6AiEarlyThreatPseudoYields', 'PseudoYields');

INSERT INTO Strategy_Priorities (StrategyType, ListType) VALUES
('CIV6AI_STRATEGY_EARLY_EXPAND', 'Civ6AiEarlyExpandPseudoYields'),
('CIV6AI_STRATEGY_EARLY_THREAT', 'Civ6AiEarlyThreatPseudoYields');

-- No favoured items: the early strategies only record the mode (early_mode
-- log, threat facts). What gets built follows the model's production preset.


-- Early settle levers: on while an AI major has 1-2 cities (Civ6AiEarlySettle in
-- Gameplay/Civ6Ai_Orders.lua). Uses the game's own expansion settlement list
-- (ExpansionSettlementBoost, the SettlementPreferences list of the vanilla
-- STRATEGY_RAPID_EXPANSION: lower settle-spot bar, so the AI wants settlers) and
-- a direct Units weight for the Settler (the vanilla UnitPriorityBoosts system).
INSERT INTO Types (Type, Kind) VALUES ('CIV6AI_STRATEGY_EARLY_SETTLE', 'KIND_VICTORY_STRATEGY');
INSERT INTO Strategies (StrategyType, VictoryType, NumConditionsNeeded) VALUES ('CIV6AI_STRATEGY_EARLY_SETTLE', NULL, 1);
INSERT INTO StrategyConditions (StrategyType, ConditionFunction, Disqualifier) VALUES
('CIV6AI_STRATEGY_EARLY_SETTLE', 'Is Not Major', 1);
INSERT INTO StrategyConditions (StrategyType, ConditionFunction, StringValue, ThresholdValue) VALUES
('CIV6AI_STRATEGY_EARLY_SETTLE', 'Call Lua Function', 'Civ6AiEarlySettle', 0);
INSERT INTO AiListTypes (ListType) VALUES ('Civ6AiSettleUnits');
INSERT INTO AiLists (ListType, System) VALUES ('Civ6AiSettleUnits', 'Units');
INSERT INTO AiFavoredItems (ListType, Item, Favored, Value) VALUES ('Civ6AiSettleUnits', 'UNIT_SETTLER', 1, 300);
-- All three lists of the vanilla STRATEGY_RAPID_EXPANSION (Victories.xml):
-- settle-spot bar, plot preferences, and pseudoyields (settler +25, land and
-- naval combat -25), plus the direct Units weight.
INSERT INTO Strategy_Priorities (StrategyType, ListType) VALUES
('CIV6AI_STRATEGY_EARLY_SETTLE', 'ExpansionSettlementBoost'),
('CIV6AI_STRATEGY_EARLY_SETTLE', 'ExpansionSettlementPreferences'),
('CIV6AI_STRATEGY_EARLY_SETTLE', 'ExpansionUnitPreferences'),
('CIV6AI_STRATEGY_EARLY_SETTLE', 'Civ6AiSettleUnits');
