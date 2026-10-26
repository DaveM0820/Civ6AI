import gzip
from pathlib import Path
from types import SimpleNamespace

from sidecar import run_civ6


def test_archive_writes_prompt_and_reply(tmp_path: Path):
    turn = SimpleNamespace(raw_model_response={"a": 1}, record={})
    p = run_civ6._archive_turn_io(tmp_path / "journal.jsonl", "PLAYER_2", {"decision": {"turn": 7}}, "WIRE", turn)
    assert p.name == "P2_T7.txt.gz"
    text = gzip.open(p, "rt", encoding="utf-8").read()
    assert "WIRE" in text and '"a":1' in text.replace(" ", "")
