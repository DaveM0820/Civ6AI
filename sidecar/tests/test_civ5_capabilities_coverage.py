"""Update Civ5 capability coverage tests for catalog-driven Apply/Net."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAPABILITIES = ROOT / "config" / "civ5-command-capabilities.json"
COMMANDS_LUA = ROOT / "artifacts" / "Civ5Ai" / "Lua" / "Civ5Ai_Commands.lua"
APPLY_LUA = ROOT / "artifacts" / "Civ5Ai" / "Lua" / "Civ5Ai_Apply.lua"
SNAPSHOT_LUA = ROOT / "artifacts" / "Civ5Ai" / "Lua" / "Civ5Ai_Snapshot.lua"


def _parse_catalog_kinds(text: str) -> set[str]:
    return set(re.findall(r'kind\s*=\s*"([^"]+)"', text))


def _parse_mp_kinds(text: str) -> set[str]:
    """Kinds whose catalog row sets mp = true (near the kind field)."""
    mp_kinds: set[str] = set()
    for match in re.finditer(
        r'\{\s*kind\s*=\s*"([^"]+)"(.*?)(?=\n\s*\{|\nend\b|\Z)',
        text,
        re.DOTALL,
    ):
        kind, body = match.group(1), match.group(2)[:500]
        if re.search(r"\bmp\s*=\s*true\b", body):
            mp_kinds.add(kind)
    return mp_kinds


def _parse_apply_handlers(text: str) -> set[str]:
    """Catalog kinds that redirect to an apply function (apply = \"_Foo\")."""
    kinds: set[str] = set()
    for match in re.finditer(
        r'\{\s*kind\s*=\s*"([^"]+)"(.*?)(?=\n\s*\{|\nend\b|\Z)',
        text,
        re.DOTALL,
    ):
        kind, body = match.group(1), match.group(2)[:800]
        if re.search(r'\bapply\s*=\s*"', body):
            kinds.add(kind)
    return kinds


class Civ5CapabilitiesCoverageTests(unittest.TestCase):
    def test_v1_kinds_have_apply_handlers(self):
        doc = json.loads(CAPABILITIES.read_text(encoding="utf-8"))
        commands_text = COMMANDS_LUA.read_text(encoding="utf-8")
        apply_kinds = _parse_apply_handlers(commands_text)
        v1_kinds = {row["kind"] for row in doc["capabilities"] if row.get("tier") == "v1"}
        exempt = {"chat"}
        missing = sorted(v1_kinds - apply_kinds - exempt)
        self.assertEqual([], missing, f"v1 kinds missing apply handler: {missing}")

    def test_v1_kinds_in_mp_table_and_net_encode(self):
        doc = json.loads(CAPABILITIES.read_text(encoding="utf-8"))
        commands_text = COMMANDS_LUA.read_text(encoding="utf-8")
        mp_kinds = _parse_mp_kinds(commands_text)
        # Net encoding is catalog-driven via Civ5Ai_Commands.EncodeNet (row.net).
        net_kinds = set()
        for match in re.finditer(
            r'\{\s*kind\s*=\s*"([^"]+)"(.*?)(?=\n\s*\{|\nend\b|\Z)',
            commands_text,
            re.DOTALL,
        ):
            kind, body = match.group(1), match.group(2)[:800]
            if re.search(r"\bnet\s*=\s*\{", body) or re.search(r'\bnet\s*=\s*"', body):
                net_kinds.add(kind)
        exempt_mp = {"chat"}
        v1_kinds = {row["kind"] for row in doc["capabilities"] if row.get("tier") == "v1"}
        missing_mp = sorted(v1_kinds - mp_kinds - exempt_mp)
        missing_net = sorted(v1_kinds - net_kinds - exempt_mp)
        self.assertEqual([], missing_mp, f"v1 kinds missing catalog mp=true: {missing_mp}")
        self.assertEqual([], missing_net, f"v1 kinds missing catalog net encode: {missing_net}")

    def test_deferred_kinds_not_in_snapshot_or_apply(self):
        doc = json.loads(CAPABILITIES.read_text(encoding="utf-8"))
        deferred = {row["kind"] for row in doc.get("deferred_capabilities", [])}
        commands_text = COMMANDS_LUA.read_text(encoding="utf-8")
        snapshot_text = SNAPSHOT_LUA.read_text(encoding="utf-8")
        apply_kinds = _parse_catalog_kinds(commands_text)
        leaked_apply = sorted(deferred & apply_kinds)
        leaked_snapshot = sorted(
            kind for kind in deferred if f'kind = "{kind}"' in snapshot_text or f"kind = '{kind}'" in snapshot_text
        )
        self.assertEqual([], leaked_apply, f"deferred kinds in catalog: {leaked_apply}")
        self.assertEqual([], leaked_snapshot, f"deferred kinds in snapshot emit: {leaked_snapshot}")

    def test_mp_kinds_subset_of_apply_kinds(self):
        commands_text = COMMANDS_LUA.read_text(encoding="utf-8")
        apply_kinds = _parse_apply_handlers(commands_text)
        mp_kinds = _parse_mp_kinds(commands_text)
        extra = sorted(mp_kinds - apply_kinds)
        self.assertEqual([], extra, f"mp kinds without apply handler: {extra}")


if __name__ == "__main__":
    unittest.main()
