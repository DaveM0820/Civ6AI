import unittest
from unittest import mock

from sidecar import civ6_attention as attention
from sidecar import civ6_prompt_coaching as coaching


class AttentionRegistryTests(unittest.TestCase):
    def test_events_come_from_provider_not_text(self):
        with mock.patch.object(coaching, "civ6_focus_fire_attention", return_value="gold explore heal"), \
             mock.patch.object(coaching, "civ6_exploration_attention", return_value=None):
            items = [i for i in attention.collect({}) if i.text == "gold explore heal"]
        self.assertEqual([(i.topic, i.event) for i in items], [("war", "FocusFire")])

    def test_dedupe_keeps_first_and_events_are_unique(self):
        with mock.patch.object(coaching, "civ6_exploration_attention", return_value="Map  dark"), \
             mock.patch.object(coaching, "civ6_naval_explore_attention", return_value="map dark"), \
             mock.patch.object(coaching, "civ6_economy_attention", return_value=["Treasury", "Gold"]):
            self.assertEqual(attention.lines({})[:1], ["Map  dark"])
            names = attention.event_names({})
        self.assertEqual(names.count("Economy"), 1)
        self.assertLess(names.index("Explore"), names.index("Economy"))

    def test_budget_protects_registry_section(self):
        from sidecar import civ6_prompt_budget

        self.assertIn(attention.SECTION, civ6_prompt_budget.PROTECTED_SECTIONS)


if __name__ == "__main__":
    unittest.main()
