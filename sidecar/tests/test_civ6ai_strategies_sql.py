"""The build-strategy SQL loads against the game's table shapes and every
'Call Lua Function' condition has a matching handler in Civ6Ai_Orders.lua."""
import pathlib
import re
import sqlite3
import unittest

MOD = pathlib.Path(__file__).resolve().parents[2] / "mod" / "Civ6Ai"

SCHEMA = """
CREATE TABLE Types (Type TEXT PRIMARY KEY, Kind TEXT NOT NULL);
CREATE TABLE Strategies (StrategyType TEXT PRIMARY KEY REFERENCES Types(Type), VictoryType TEXT, NumConditionsNeeded INTEGER NOT NULL DEFAULT 1);
CREATE TABLE StrategyConditions (StrategyType TEXT NOT NULL REFERENCES Strategies(StrategyType), ConditionFunction TEXT NOT NULL,
  StringValue TEXT, ThresholdValue INTEGER DEFAULT 0, Forbidden BOOLEAN DEFAULT 0, Disqualifier BOOLEAN DEFAULT 0);
CREATE TABLE AiListTypes (ListType TEXT PRIMARY KEY);
CREATE TABLE AiLists (ListType TEXT NOT NULL REFERENCES AiListTypes(ListType), LeaderType TEXT, AgendaType TEXT, System TEXT NOT NULL);
CREATE TABLE Strategy_Priorities (StrategyType TEXT NOT NULL REFERENCES Strategies(StrategyType), ListType TEXT NOT NULL REFERENCES AiListTypes(ListType));
CREATE TABLE AiFavoredItems (ListType TEXT NOT NULL REFERENCES AiListTypes(ListType), Item TEXT NOT NULL, Favored BOOLEAN DEFAULT 0,
  Value INTEGER DEFAULT 0, StringVal TEXT, TooltipString TEXT);
"""


class StrategiesSqlTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        # Vanilla list the mod reuses (Base Victories.xml, STRATEGY_RAPID_EXPANSION).
        self.db.execute("INSERT INTO AiListTypes (ListType) VALUES ('ExpansionSettlementBoost')")
        self.db.executescript((MOD / "Data" / "Civ6Ai_Strategies.sql").read_text())

    def test_each_strategy_has_one_single_item_list(self):
        rows = self.db.execute("""SELECT sp.StrategyType, COUNT(f.Item) FROM Strategy_Priorities sp
                                  JOIN AiFavoredItems f ON f.ListType = sp.ListType
                                  WHERE sp.StrategyType LIKE 'CIV6AI_STRATEGY_FORCE_%'
                                  GROUP BY sp.StrategyType""").fetchall()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(n == 1 for _, n in rows))

    def test_lua_handlers_exist_for_conditions(self):
        lua = (MOD / "Gameplay" / "Civ6Ai_Orders.lua").read_text()
        names = [r[0] for r in self.db.execute(
            "SELECT StringValue FROM StrategyConditions WHERE ConditionFunction = 'Call Lua Function'")]
        self.assertEqual(len(names), 6)
        for name in names:
            self.assertRegex(lua, r'(fn = "%s"|%s = ")' % (re.escape(name), re.escape(name)))

    def test_early_strategies_force_no_builds(self):
        rows = self.db.execute("SELECT COUNT(*) FROM AiFavoredItems WHERE ListType LIKE 'Civ6AiEarly%'").fetchone()
        self.assertEqual(rows[0], 0)

    def test_modinfo_loads_the_sql(self):
        info = (MOD / "Civ6Ai.modinfo").read_text()
        self.assertIn("<UpdateDatabase", info)
        self.assertEqual(info.count("Data/Civ6Ai_Strategies.sql"), 2)


if __name__ == "__main__":
    unittest.main()


class EarlySettleSqlTests(unittest.TestCase):
    def test_early_settle_uses_vanilla_expansion_list_and_settler_weight(self):
        db = sqlite3.connect(":memory:")
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(SCHEMA)
        db.execute("INSERT INTO AiListTypes (ListType) VALUES ('ExpansionSettlementBoost')")
        db.executescript((MOD / "Data" / "Civ6Ai_Strategies.sql").read_text())
        lists = {r[0] for r in db.execute(
            "SELECT ListType FROM Strategy_Priorities WHERE StrategyType = 'CIV6AI_STRATEGY_EARLY_SETTLE'")}
        self.assertEqual(lists, {"ExpansionSettlementBoost", "Civ6AiSettleUnits"})
        row = db.execute("SELECT f.Item, f.Value, l.System FROM AiFavoredItems f JOIN AiLists l ON l.ListType = f.ListType "
                         "WHERE f.ListType = 'Civ6AiSettleUnits'").fetchone()
        self.assertEqual(row, ("UNIT_SETTLER", 300, "Units"))
