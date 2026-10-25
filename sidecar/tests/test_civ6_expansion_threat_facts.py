"""Expansion/threat facts reach the prompt as plain lines; threat counts only
visible units and a tie is not a threat; the local purchase path sends a price."""
import pathlib
import unittest

from sidecar import civ6_wire

MOD = pathlib.Path(__file__).resolve().parents[2] / "mod" / "Civ6Ai"


class ExpansionThreatFactsTests(unittest.TestCase):
    def test_lines(self):
        summary = {
            "expansion": {"cities": 1, "settlers_on_map": 0, "cities_building_settler": 1,
                          "met_majors": [{"player_id": "PLAYER_3", "cities": 2}]},
            "threat": {"radius": 6, "defenders": 1,
                       "hostiles": [{"unit_type": "UNIT_WARRIOR", "owner_kind": "barbarian",
                                     "owner_id": "PLAYER_63", "x": 4, "y": 5, "distance": 3,
                                     "nearest_city": "Rome"}],
                       "camps": [{"x": 6, "y": 6, "distance": 4, "nearest_city": "Rome"}]},
        }
        text = "\n".join(civ6_wire._expansion_threat_lines(summary))
        self.assertIn("you 1; met majors PLAYER_3=2", text)
        self.assertIn("cities building a settler 1", text)
        self.assertIn("UNIT_WARRIOR (barbarian PLAYER_63) at (4,5), 3 tiles from Rome", text)
        self.assertIn("barbarian camp at (6,6)", text)
        self.assertIn("your land combat units there 1", text)
        self.assertEqual(civ6_wire._expansion_threat_lines({}), [])

    def test_threat_rule_is_strict_and_visible(self):
        for path, needle in (("Gameplay/Civ6Ai_Orders.lua", "return hostiles > defenders, hostiles, defenders"),
                             ("InGame/Civ6Ai_Production.lua", "local threat = hostiles > defenders")):
            src = (MOD / path).read_text()
            self.assertIn(needle, src)
            self.assertIn("IsVisible", src)
            self.assertIn("IsRevealed", src)
            self.assertNotIn("defenders <= hostiles", src)

    def test_local_purchase_sends_engine_price(self):
        src = (MOD / "InGame" / "Civ6Ai_Apply.lua").read_text()
        body = src.split('if kind == "purchase_item" then', 1)[1].split('if kind == "purchase_tile"', 1)[0]
        self.assertIn("Civ6Ai_Snapshot._PurchaseCost(", body)
        self.assertIn("faith, cost)", body)


if __name__ == "__main__":
    unittest.main()


def test_schema_allows_expansion_and_threat_summary():
    import json
    from pathlib import Path
    import jsonschema
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / "schemas" / "decision-input-v2.json").read_text(encoding="utf-8"))
    summary = dict(schema["$defs"]["summary"])
    summary["$defs"] = schema["$defs"]
    doc = {k: [] for k in summary["required"]}
    doc["expansion"] = {"cities": 1, "settlers_on_map": 1}
    doc["threat"] = {"defenders": 1, "hostiles": []}
    jsonschema.validate(doc, summary)


def test_schema_allows_unit_goal_set_turn():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / "schemas" / "decision-input-v2.json").read_text(encoding="utf-8"))
    goal = schema["$defs"]["owned_unit"]["properties"]["goal"]
    assert "set_turn" in goal["properties"]
    import jsonschema
    jsonschema.validate({"x": 1, "y": 2, "intent": "settle", "A": 1, "eta": 3, "set_turn": 30}, goal)
