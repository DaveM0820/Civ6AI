import os
import unittest
from unittest import mock

from sidecar import civ6_prompt_coaching as coaching
from sidecar import civ6_wire


def _snap():
    return {"schema_version": "civ6ai-input/1", "personality": {"leader_name": "Seondeok"}}


class Civ6PrimerTests(unittest.TestCase):
    def test_primer_is_first_and_static(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CIV6AI_CIV6_PRIMER", None)
            a = civ6_wire.build_civ6_role_instruction(_snap())
            b = civ6_wire.build_civ6_role_instruction(_snap())
        self.assertTrue(a.startswith(coaching.CIV6_GAME_PRIMER))
        self.assertEqual(a, b)
        self.assertIn("Seondeok", a)
        self.assertTrue(1500 <= len(coaching.CIV6_GAME_PRIMER) <= 3000)
        for kw in ("high-elo", "adjacency", "build charges", "luxury", "strategic", "eurekas", "envoys",
                   "zone of control", "tall vs wide", "Victory paths", "never"):
            self.assertIn(kw, coaching.CIV6_GAME_PRIMER)

    def test_primer_toggle_off(self):
        with mock.patch.dict(os.environ, {"CIV6AI_CIV6_PRIMER": "0"}):
            text = civ6_wire.build_civ6_role_instruction(_snap())
        self.assertNotIn("CIVILIZATION VI PRIMER", text)
        self.assertTrue(text.startswith("You are"))


if __name__ == "__main__":
    unittest.main()
