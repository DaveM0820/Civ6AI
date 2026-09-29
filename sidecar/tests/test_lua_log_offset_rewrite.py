import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "scripts" / "testbed", ROOT / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import civ6_lua_log_bridge as bridge  # noqa: E402


class LuaLogOffsetRewriteTest(unittest.TestCase):
    def test_rewritten_log_resets_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "offset.json"
            log = Path(tmp) / "Lua.log"
            log.write_bytes(b"old boot line\n" * 1000)
            bridge.store_log_offset(state, log, log.stat().st_size)
            self.assertEqual(bridge.resolve_log_offset(state, log), log.stat().st_size)
            # Civ6 reboot: log rewritten, still smaller than the old offset.
            log.write_bytes(b"new boot\n")
            self.assertEqual(bridge.resolve_log_offset(state, log), 0)
            # Log rewritten and already grown past the old offset: head differs.
            log.write_bytes(b"NEW game header\n" * 5000)
            self.assertEqual(bridge.resolve_log_offset(state, log), 0)

    def test_growing_log_keeps_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "offset.json"
            log = Path(tmp) / "Lua.log"
            log.write_bytes(b"x" * 2000)
            bridge.store_log_offset(state, log, 2000)
            with log.open("ab") as handle:
                handle.write(b"more\n")
            self.assertEqual(bridge.resolve_log_offset(state, log), 2000)

    def test_legacy_plain_integer_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "offset.txt"
            log = Path(tmp) / "Lua.log"
            log.write_bytes(b"y" * 100)
            state.write_text("50", encoding="utf-8")
            self.assertEqual(bridge.resolve_log_offset(state, log), 50)
            state.write_text("5000", encoding="utf-8")
            self.assertEqual(bridge.resolve_log_offset(state, log), 0)


if __name__ == "__main__":
    unittest.main()
