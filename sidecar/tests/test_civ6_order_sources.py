"""Host fallbacks are logged as source=fallback in turn_metrics."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sidecar import civ6_apply_results as results
from sidecar import pipeline_v2 as pipeline


class OrderSourceMetricsTests(unittest.TestCase):
    def test_model_and_fallback_rows_are_counted_in_turn_metrics(self):
        rows = [
            {"event": "apply_result", "player_id": "PLAYER_2", "turn": 6,
             "kind": "explore", "ok": True, "source": "model", "command_id": "CMD_E"},
            {"event": "apply_result", "player_id": "PLAYER_2", "turn": 6,
             "kind": "city_attack", "ok": True, "source": "model", "command_id": "CMD_S"},
            {"event": "apply_result", "player_id": "PLAYER_2", "turn": 6,
             "kind": "attack_target", "ok": True, "source": "fallback",
             "command_id": "AUTO_U_9_10_11"},
            {"event": "apply_result", "player_id": "PLAYER_2", "turn": 6,
             "kind": "explore", "ok": True, "command_id": "AUTO_E_8"},
        ]
        fields = results.order_source_fields(rows)
        self.assertEqual(2, fields["order_source_model"])
        self.assertEqual(2, fields["order_source_fallback"])
        self.assertEqual(
            ["model", "model", "fallback", "fallback"],
            [row["source"] for row in fields["order_sources"]],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            player = root / "PLAYER_2"
            player.mkdir()
            pipeline.append_turn_metrics(root, {
                "player_id": "PLAYER_2", "turn": 6, "status": "ok",
                **results.order_source_fields([]),
            })
            self.assertTrue(results.merge_order_sources_into_metrics(root, "PLAYER_2", 6, rows))
            event = json.loads((root / "turn_metrics.jsonl").read_text().splitlines()[-1])
            self.assertEqual(2, event["order_source_model"])
            self.assertEqual(2, event["order_source_fallback"])
            self.assertEqual("fallback", event["order_sources"][2]["source"])


if __name__ == "__main__":
    unittest.main()
