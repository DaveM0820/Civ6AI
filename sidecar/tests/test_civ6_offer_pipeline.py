import ast
import unittest
from pathlib import Path

from sidecar import civ6_legality as legality

SIDECAR = Path(__file__).resolve().parents[1]


class OfferPipelineTests(unittest.TestCase):
    def test_only_legality_writes_snapshot_offers(self):
        offenders = []
        for path in sorted(SIDECAR.glob("civ6_*.py")):
            if path.name == "civ6_legality.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                for t in node.targets if isinstance(node, ast.Assign) else []:
                    if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == "snapshot"
                            and isinstance(t.slice, ast.Constant) and t.slice.value == "legal_commands"):
                        offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual([], offenders)

    def test_registered_filters_resolve(self):
        for name in legality.OFFER_FILTERS:
            self.assertTrue(callable(legality.offer_filter(name)), name)

    def test_add_offer_dedupes(self):
        snap = {}
        self.assertEqual("A", legality.add_offer(snap, {"command_id": "A"}))
        self.assertEqual("A", legality.add_offer(snap, {"command_id": "A"}))
        self.assertEqual(1, len(snap["legal_commands"]))

    def test_pact_reason_text(self):
        self.assertEqual("no alliance while at war", legality.reason_text("no_alliance_at_war"))
        self.assertEqual("peace needs a war", legality.reason_text("peace_not_at_war"))


if __name__ == "__main__":
    unittest.main()
