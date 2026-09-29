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
