"""Engine-locking popups close through their own Close() (Civ6Ai_ExclusivePopup),
never through UIManager:DequeuePopup, which kept the engine lock (T28 freeze)."""
import pathlib
import re
import unittest
import xml.etree.ElementTree as ET

MOD = pathlib.Path(__file__).resolve().parents[2] / "mod" / "Civ6Ai"
EXCLUSIVE = [
    "NaturalDisasterPopup", "NaturalWonderPopup", "WonderBuiltPopup",
    "ProjectBuiltPopup", "EraCompletePopup", "CreateCorporationPopup",
]


class ExclusivePopupTests(unittest.TestCase):
    def setUp(self):
        self.modinfo = ET.parse(MOD / "Civ6Ai.modinfo").getroot()

    def test_each_popup_is_wrapped_and_shipped(self):
        replaced = {
            r.findtext("Properties/LuaContext"): r.findtext("Properties/LuaReplace")
            for r in self.modinfo.iter("ReplaceUIScript")
        }
        files = {f.text for f in self.modinfo.find("Files")}
        for name in EXCLUSIVE:
            path = f"InGame/Civ6Ai_{name}.lua"
            self.assertEqual(replaced.get(name), path)
            self.assertIn(path, files)
            text = (MOD / path).read_text()
            self.assertIn(f'include("{name}")', text)
            self.assertIn(f'Civ6Ai_ExclusivePopup.Install("{name}", Close)', text)
        self.assertIn("InGame/Civ6Ai_ExclusivePopup.lua", files)

    def test_autotest_does_not_dequeue_exclusive_popups(self):
        src = (MOD / "InGame" / "Civ6Ai_Autotest.lua").read_text()
        body = src.split("function Civ6Ai_Autotest._CloseQueuedPopups()", 1)[1].split("\nend\n", 1)[0]
        listed = set(re.findall(r'^\s*"(\w+)",', body, re.M))
        self.assertTrue(listed)
        self.assertFalse(listed & set(EXCLUSIVE))


if __name__ == "__main__":
    unittest.main()
