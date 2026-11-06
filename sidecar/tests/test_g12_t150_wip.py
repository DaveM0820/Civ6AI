"""g12 T150 WIP: map-cap recovery, credit 402, settle.nearby, self-tile copy."""
from __future__ import annotations

import unittest
from unittest import mock

from sidecar import civ6_apply_results as apply
from sidecar import civ6_legality as legality
from sidecar import civ6_prompt_coaching as coaching
from sidecar import pipeline_v2 as pipeline


class VisibilityCellTests(unittest.TestCase):
    def test_visibility_cell_at_viewport_origin(self):
        snap = {
            "known_map": {
                "viewport": {"x0": 10, "y0": 20, "x1": 12, "y1": 21},
                "visibility_grid": ["~~~", "o.^"],
            }
        }
        self.assertEqual(pipeline.visibility_cell_at(snap, 10, 20), "~")
        self.assertEqual(pipeline.visibility_cell_at(snap, 11, 21), ".")
        self.assertEqual(pipeline.visibility_cell_at(snap, 12, 21), "^")
        self.assertIsNone(pipeline.visibility_cell_at(snap, 9, 20))

    def test_apply_plot_facts_uses_grid_when_plots_capped(self):
        snap = {
            "player_id": "PLAYER_1",
            "known_map": {
                "viewport": {"x0": 0, "y0": 0, "x1": 2, "y1": 0},
                "visibility_grid": ["~.o"],
                "plots": [],  # capped away
            },
            "your_units": [],
        }
        self.assertEqual(apply._plot_facts(snap, 0, 0, "PLAYER_1"), ["water"])
        self.assertEqual(apply._plot_facts(snap, 2, 0, "PLAYER_1"), ["water"])
        self.assertEqual(apply._plot_facts(snap, 1, 0, "PLAYER_1"), [])
        self.assertEqual(apply._plot_facts(snap, 5, 5, "PLAYER_1"), ["tile not explored"])

    def test_embarked_text_from_grid_when_plot_missing(self):
        unit = {"domain_id": "DOMAIN_LAND", "x": 1, "y": 0}
        snap = {
            "known_map": {
                "viewport": {"x0": 0, "y0": 0, "x1": 2, "y1": 0},
                "visibility_grid": ["~o~"],
                "plots": [],
            }
        }
        self.assertEqual(coaching.embarked_text(unit, snap), "embarked on ocean (cities are founded on land)")


class CreditExhaustedTests(unittest.TestCase):
    def test_http_402_is_credit_exhausted(self):
        self.assertEqual(pipeline._http_error_category(402), "credit_exhausted")

    def test_circuit_breaker_opens_on_one_402(self):
        cb = pipeline.CircuitBreaker({})
        cb.record_failure("PLAYER_2", "credit_exhausted", "HTTP 402")
        self.assertTrue(cb.open("PLAYER_2"))
        self.assertGreaterEqual(cb.failures.get("PLAYER_2", 0), 3)


class SettleNearbyRestoredTests(unittest.TestCase):
    def test_settler_fact_includes_nearby_sites(self):
        unit = {
            "unit_id": "settler_1",
            "name": "Settler",
            "domain_id": "DOMAIN_LAND",
            "x": 5,
            "y": 5,
            "settle": {
                "here_ok": False,  # must be false to surface nearby

                "sites": [
                    {"x": 6, "y": 5, "path_turns": 1, "fresh_water": True},
                    {"x": 7, "y": 5, "path_turns": 2},
                ],
            },
        }
        snap = {"known_map": {"plots": [{"x": 5, "y": 5, "terrain_id": "TERRAIN_GRASS"}]}, "your_units": [unit]}
        lines = coaching.settler_fact_lines("settler_1", unit, snap)
        blob = "\n".join(lines)
        self.assertIn("settle.nearby", blob)

    def test_settler_nearby_hidden_when_foundcity_legal_here(self):
        unit = {
            "unit_id": "settler_1",
            "name": "Settler",
            "domain_id": "DOMAIN_LAND",
            "x": 5,
            "y": 5,
            "settle": {
                "here_ok": True,
                "sites": [{"x": 6, "y": 5, "path_turns": 1}],
            },
        }
        snap = {"known_map": {"plots": [{"x": 5, "y": 5, "terrain_id": "TERRAIN_GRASS"}]}, "your_units": [unit]}
        blob = "\n".join(coaching.settler_fact_lines("settler_1", unit, snap))
        self.assertNotIn("settle.nearby", blob)


class SelfTileCopyTests(unittest.TestCase):
    def test_self_tile_message_is_explicit(self):
        self.assertIn("own tile", legality.REASON_TEXT["self_tile_move"].lower())
        self.assertIn("already on that tile", legality.REASON_TEXT["self_tile_move"])
        self.assertIn("Skip", legality.REASON_TEXT["self_tile_move"])
