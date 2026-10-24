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

-- Early-game build order for engine-AI seats (the local fill uses the same
-- rule in InGame/Civ6Ai_Production.lua). Active for a seat the model drives
-- (any Civ6Ai priority set) with fewer than 3 cities by turn 60. EXPAND favours
-- settlers, then builders, and drops scouts and spare army; THREAT (hostile land
-- combat units, a camp within 4 or a war outnumber our army near our cities;
-- scouts do not count) favours land combat units without holding settlers back,
-- and clears once our army near the cities outnumbers them. Exclusive.
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

INSERT INTO AiFavoredItems (ListType, Item, Favored, Value) VALUES
('Civ6AiEarlyExpandPseudoYields', 'PSEUDOYIELD_UNIT_SETTLER',          1, 600),
('Civ6AiEarlyExpandPseudoYields', 'PSEUDOYIELD_IMPROVEMENT',           1, 150),
('Civ6AiEarlyExpandPseudoYields', 'PSEUDOYIELD_UNIT_EXPLORER',         1, -200),
('Civ6AiEarlyExpandPseudoYields', 'PSEUDOYIELD_UNIT_COMBAT',           1, -40),
('Civ6AiEarlyExpandPseudoYields', 'PSEUDOYIELD_WONDER',                1, -80),
('Civ6AiEarlyThreatPseudoYields', 'PSEUDOYIELD_UNIT_COMBAT',           1, 300),
('Civ6AiEarlyThreatPseudoYields', 'PSEUDOYIELD_STANDING_ARMY_NUMBER',  1, 100),
('Civ6AiEarlyThreatPseudoYields', 'PSEUDOYIELD_UNIT_SETTLER',          1, 0),
('Civ6AiEarlyThreatPseudoYields', 'PSEUDOYIELD_UNIT_EXPLORER',         1, -200);
