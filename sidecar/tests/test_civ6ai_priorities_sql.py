"""The build-priority SQL (generated from sidecar/civ6_priorities.py) loads
against the game's table shapes, skips items the rulesets lack, and every
'Call Lua Function' condition has a registration in Civ6Ai_Orders.lua."""
import pathlib
import re
import sqlite3
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
MOD = ROOT / "mod" / "Civ6Ai"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from sidecar import civ6_priorities as P  # noqa: E402
from sidecar.tests.test_civ6ai_strategies_sql import SCHEMA  # noqa: E402
import gen_priorities  # noqa: E402

DEFS = """
CREATE TABLE Yields (YieldType TEXT PRIMARY KEY);
CREATE TABLE PseudoYields (PseudoYieldType TEXT PRIMARY KEY);
CREATE TABLE UnitPromotionClasses (PromotionClassType TEXT PRIMARY KEY);
CREATE TABLE Districts (DistrictType TEXT PRIMARY KEY);
CREATE TABLE DistrictReplaces (CivUniqueDistrictType TEXT, ReplacesDistrictType TEXT);
"""

FIELDS = {"yields": ("Yields", "YieldType"), "pseudo": ("PseudoYields", "PseudoYieldType"),
          "classes": ("UnitPromotionClasses", "PromotionClassType"), "districts": ("Districts", "DistrictType")}


def all_items():
    out = {f: set() for f in FIELDS}
    for cat in P.CATEGORIES:
        for f in FIELDS:
            out[f].update((cat.get(f) or {}).keys())
    return out


class PrioritiesSqlTests(unittest.TestCase):
    def load(self, drop=()):
        db = sqlite3.connect(":memory:")
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(SCHEMA + DEFS)
        for f, items in all_items().items():
            table, col = FIELDS[f]
            for item in items:
                if item not in drop:
                    db.execute(f"INSERT INTO {table} ({col}) VALUES (?)", (item,))
        db.execute("INSERT INTO Districts VALUES ('DISTRICT_ACROPOLIS')")
        db.execute("INSERT INTO DistrictReplaces VALUES ('DISTRICT_ACROPOLIS', 'DISTRICT_THEATER')")
        db.executescript((MOD / "Data" / "Civ6Ai_Priorities.sql").read_text())
        return db

    def test_generated_file_is_current(self):
        self.assertEqual((MOD / "Data" / "Civ6Ai_Priorities.sql").read_text(), gen_priorities.build())
        lua = (MOD / "Gameplay" / "Civ6Ai_Orders.lua").read_text()
        self.assertIn(gen_priorities.lua_block(), lua)

    def test_one_strategy_per_category_and_level(self):
        db = self.load()
        n = db.execute("SELECT COUNT(*) FROM Strategies WHERE StrategyType LIKE 'CIV6AI_PRIO_%'").fetchone()[0]
        self.assertEqual(n, len(P.CATEGORIES) * len(P.LEVELS))
        ids = [c["id"] for c in P.CATEGORIES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_levels_scale_values(self):
        db = self.load()
        cat = P.BY_KEY["science_victory"]
        item, base = next(iter(cat["yields"].items()))
        for level in P.LEVELS:
            v = db.execute("SELECT Value FROM AiFavoredItems WHERE ListType = ? AND Item = ?",
                           (P.strategy_type(cat, level) + "_Yields", item)).fetchone()[0]
            self.assertEqual(v, P.scaled(base, level))
        self.assertGreaterEqual(min(r[0] for r in db.execute("SELECT Value FROM AiFavoredItems")), -100)

    def test_missing_items_are_skipped_not_fatal(self):
        db = self.load(drop={"DISTRICT_HARBOR", "PSEUDOYIELD_UNIT_NAVAL_COMBAT"})
        n = db.execute("SELECT COUNT(*) FROM AiFavoredItems WHERE Item IN "
                       "('DISTRICT_HARBOR', 'PSEUDOYIELD_UNIT_NAVAL_COMBAT')").fetchone()[0]
        self.assertEqual(n, 0)

    def test_unique_district_replacements_favoured(self):
        db = self.load()
        n = db.execute("SELECT COUNT(*) FROM AiFavoredItems WHERE Item = 'DISTRICT_ACROPOLIS'").fetchone()[0]
        with_theater = sum(1 for c in P.CATEGORIES if "DISTRICT_THEATER" in (c.get("districts") or {}))
        self.assertEqual(n, with_theater * len(P.LEVELS))

    def test_conditions_match_lua_registration(self):
        db = self.load()
        names = {r[0] for r in db.execute(
            "SELECT StringValue FROM StrategyConditions WHERE ConditionFunction = 'Call Lua Function' "
            "AND StringValue LIKE 'Civ6AiPrio_%'")}
        expected = {P.lua_fn(c, lv) for c in P.CATEGORIES for lv in P.LEVELS}
        self.assertEqual(names, expected)
        lua = (MOD / "Gameplay" / "Civ6Ai_Orders.lua").read_text()
        self.assertIn('GameEvents["Civ6AiPrio_" .. cat.id .. "_" .. level]', lua)
        for c in P.CATEGORIES:
            self.assertRegex(lua, r'\{ id = %d, key = "%s"' % (c["id"], re.escape(c["key"])))

    def test_every_strategy_disqualifies_minors(self):
        db = self.load()
        n = db.execute("SELECT COUNT(*) FROM StrategyConditions WHERE ConditionFunction = 'Is Not Major' "
                       "AND Disqualifier = 1 AND StrategyType LIKE 'CIV6AI_PRIO_%'").fetchone()[0]
        self.assertEqual(n, len(P.CATEGORIES) * len(P.LEVELS))

    def test_modinfo_loads_the_sql(self):
        info = (MOD / "Civ6Ai.modinfo").read_text()
        self.assertEqual(info.count("Data/Civ6Ai_Priorities.sql"), 2)
        self.assertEqual(info.count("Data/Civ6Ai_Strategies.sql"), 2)


if __name__ == "__main__":
    unittest.main()
