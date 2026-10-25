import unittest
from pathlib import Path

from sidecar import civ6_priorities as P

try:
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover
    LuaRuntime = None

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = ROOT / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Production.lua"


class SettlersOnlyPresetTest(unittest.TestCase):
    def test_preset_is_ancient_and_parses(self):
        preset = P.PRESET_BY_KEY["settlers_only"]
        self.assertEqual(int(preset["min_era"]), 0)
        self.assertEqual(P.preset_levels("settlers_only"), {P.BY_KEY["settlers_only"]["id"]: 3})
        self.assertIn("settlers only", preset["desc"])
        self.assertIn(preset, P.available_presets({}))


@unittest.skipIf(LuaRuntime is None, "lupa not installed")
class SettlersOnlyFillTest(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(PRODUCTION.read_text(encoding="utf-8"))

    def _run(self, ids, on):
        return self.lua.execute(
            "local opts = {}\n"
            + "".join(f"opts[#opts+1] = {{ id = '{i}', tags = {{}} }}\n" for i in ids)
            + "local lv = {}\n"
            + (f"lv[Civ6Ai_Production.PRIORITY_KEY_ID.settlers_only] = 3\n" if on else "")
            + "local out, note = Civ6Ai_Production.SettlersOnly(opts, { levels = lv })\n"
            + "return #out, note, out[1] and out[1].id\n"
        )

    def test_keeps_only_settler(self):
        self.assertEqual(self._run(["UNIT_BUILDER", "UNIT_SETTLER", "BUILDING_MONUMENT"], True), (1, "settler", "UNIT_SETTLER"))

    def test_falls_back_when_no_settler(self):
        n, note, _ = self._run(["UNIT_BUILDER", "BUILDING_MONUMENT"], True)
        self.assertEqual((n, note), (2, "fallback"))

    def test_off_is_untouched(self):
        n, note, _ = self._run(["UNIT_BUILDER", "UNIT_SETTLER"], False)
        self.assertEqual((n, note), (2, None))


if __name__ == "__main__":
    unittest.main()


class SettlersOnlyWeightTest(unittest.TestCase):
    def test_all_in_settler_dominates_and_rivals_clamped(self):
        cat = P.BY_KEY["settlers_only"]
        self.assertEqual(P.scaled(cat["pseudo"]["PSEUDOYIELD_UNIT_SETTLER"], 3), 1000)
        self.assertEqual(P.scaled(cat["pseudo"]["PSEUDOYIELD_IMPROVEMENT"], 3), -100)
