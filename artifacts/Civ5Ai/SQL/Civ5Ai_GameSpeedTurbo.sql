-- Civ5Ai: GAMESPEED_TURBO (~50% of Standard; Quick is ~67%).
-- Clone Quick's GameSpeeds row AND GameSpeed_Turns. Missing TurnsPerIncrement
-- is an integer divide-by-zero in CvGameCore at calendar init.

DELETE FROM GameSpeed_Turns WHERE GameSpeedType = 'GAMESPEED_TURBO';
DELETE FROM GameSpeeds WHERE Type = 'GAMESPEED_TURBO';

CREATE TEMP TABLE civ5ai_turbo AS
SELECT * FROM GameSpeeds WHERE Type = 'GAMESPEED_QUICK' LIMIT 1;

UPDATE civ5ai_turbo SET
  Type = 'GAMESPEED_TURBO',
  Description = 'TXT_KEY_GAMESPEED_TURBO',
  Help = 'TXT_KEY_GAMESPEED_TURBO_HELP',
  ID = (SELECT IFNULL(MAX(ID), -1) + 1 FROM GameSpeeds);

INSERT INTO GameSpeeds SELECT * FROM civ5ai_turbo;
DROP TABLE civ5ai_turbo;

INSERT INTO GameSpeed_Turns (GameSpeedType, MonthIncrement, TurnsPerIncrement)
SELECT
  'GAMESPEED_TURBO',
  MonthIncrement,
  MAX(1, CAST(TurnsPerIncrement * 50 / 67 AS INTEGER))
FROM GameSpeed_Turns
WHERE GameSpeedType = 'GAMESPEED_QUICK';

UPDATE GameSpeeds SET
  DealDuration = MAX(8, CAST(DealDuration * 50 / 67 AS INTEGER)),
  GrowthPercent = 50,
  TrainPercent = 50,
  ConstructPercent = 50,
  CreatePercent = 50,
  ResearchPercent = 50,
  GoldPercent = 50,
  GoldGiftMod = 150,
  BuildPercent = 50,
  ImprovementPercent = 50,
  GreatPeoplePercent = 50,
  CulturePercent = 50,
  FaithPercent = 50,
  BarbPercent = 50,
  FeatureProductionPercent = 50,
  UnitDiscoverPercent = 50,
  UnitHurryPercent = 50,
  UnitTradePercent = 50,
  GoldenAgePercent = 70,
  HurryPercent = 100,
  InflationPercent = 50,
  InflationOffset = -45,
  ReligiousPressureAdjacentCity = 110,
  VictoryDelayPercent = 50,
  MinorCivElectionFreqMod = 50,
  OpinionDurationPercent = 50,
  SpyRatePercent = 50,
  PeaceDealDuration = MAX(5, CAST(PeaceDealDuration * 50 / 67 AS INTEGER)),
  RelationshipDuration = MAX(10, CAST(RelationshipDuration * 50 / 67 AS INTEGER)),
  LeaguePercent = 50
WHERE Type = 'GAMESPEED_TURBO';

UPDATE GameSpeeds SET
  DifficultyBonusPercent = 50,
  InstantYieldPercent = 50,
  ExperiencePercent = 50,
  TradeRouteSpeedMod = 50,
  MilitaryRatingDecayPercent = 40
WHERE Type = 'GAMESPEED_TURBO';

INSERT OR IGNORE INTO Language_en_US (Tag, Text) VALUES
  ('TXT_KEY_GAMESPEED_TURBO', 'Turbo');
INSERT OR IGNORE INTO Language_en_US (Tag, Text) VALUES
  ('TXT_KEY_GAMESPEED_TURBO_HELP', 'Faster than Quick. Production, research, and growth take about half as long as Standard.');
UPDATE Language_en_US SET Text = 'Turbo' WHERE Tag = 'TXT_KEY_GAMESPEED_TURBO';
UPDATE Language_en_US SET Text = 'Faster than Quick. Production, research, and growth take about half as long as Standard.'
WHERE Tag = 'TXT_KEY_GAMESPEED_TURBO_HELP';
