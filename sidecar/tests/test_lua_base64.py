import base64
import os
import pathlib
import time
import unittest

try:
    import lupa
except ImportError:  # pragma: no cover
    lupa = None

UTIL = pathlib.Path(__file__).resolve().parents[2] / "mod" / "Civ6Ai" / "InGame" / "Civ6Ai_Util.lua"


@unittest.skipIf(lupa is None, "lupa not installed")
class LuaBase64Test(unittest.TestCase):
    def setUp(self):
        src = UTIL.read_bytes()
        ws_start = src.index(b"-- Lua %s matches byte 0xA0")
        ws_end = src.index(b"function Civ6Ai_Util.EscapeJson")
        a = src.index(b"-- Base64 via")
        b = src.index(b"function Civ6Ai_Util.DumpBlob(")
        self.lua = lupa.LuaRuntime(encoding=None)
        self.lua.execute(b"Civ6Ai_Util={}")
        self.lua.execute(src[ws_start:ws_end])
        self.lua.execute(src[a:b])
        self.collapse = self.lua.eval(b"Civ6Ai_Util.CollapseAsciiWS")
        self.enc = self.lua.eval(b"Civ6Ai_Util.Base64Encode")
        self.dec = self.lua.eval(b"Civ6Ai_Util.Base64Decode")

    def test_matches_python_and_roundtrips(self):
        for n in list(range(1, 12)) + [1000]:
            for _ in range(10):
                data = os.urandom(n)
                encoded = self.enc(data)
                self.assertEqual(encoded, base64.b64encode(data))
                self.assertEqual(self.dec(encoded), data)

    def test_collapse_ascii_ws_preserves_utf8_pieta(self):
        # In-game Lua strings are 8-bit (UTF-8 bytes). lupa encoding=None matches that.
        pieta = "Piet\u00e0 (Sculpture)".encode("utf-8")
        collapsed = self.collapse(pieta)
        self.assertEqual(pieta, collapsed)
        spaced = "Piet\u00e0  (Sculpture)".encode("utf-8")
        self.assertEqual("Piet\u00e0 (Sculpture)".encode("utf-8"), self.collapse(spaced))

    def test_large_snapshot_is_fast(self):
        data = os.urandom(60000)
        start = time.time()
        encoded = self.enc(data)
        self.assertLess(time.time() - start, 1.0)
        self.assertEqual(encoded, base64.b64encode(data))


if __name__ == "__main__":
    unittest.main()
