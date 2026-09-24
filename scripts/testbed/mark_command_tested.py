"""Mark command kinds as runtime tested in capabilities JSON after in-game proof."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CAPABILITIES_PATH = ROOT / "config" / "command-capabilities-v2.json"


def mark_tested(kinds: list[str], path: Path = CAPABILITIES_PATH) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    updated: list[str] = []
    for row in data.get("capabilities", []):
        if not isinstance(row, dict):
            continue
        kind = row.get("kind")
        if kind in kinds:
            if row.get("runtime") != "tested":
                row["runtime"] = "tested"
                updated.append(kind)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return updated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("kinds", nargs="+")
    args = parser.parse_args()
    updated = mark_tested(args.kinds)
    print(json.dumps({"updated": updated}, indent=2))


if __name__ == "__main__":
    main()
