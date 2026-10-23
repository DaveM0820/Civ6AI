import os
import unittest
from unittest import mock

from sidecar import settings


class SettingsTests(unittest.TestCase):
    def test_canonical_wins_then_aliases_in_order(self):
        env = {"CIV5_FOCUS_MODEL_IMAGE_SIZE": "100", "CIV5AI_FOCUS_MODEL_IMAGE_SIZE": "200"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("CIV6AI_FOCUS_MODEL_IMAGE_SIZE", None)
            self.assertEqual("200", settings.get("CIV6AI_FOCUS_MODEL_IMAGE_SIZE"))
            os.environ["CIV6AI_FOCUS_MODEL_IMAGE_SIZE"] = "300"
            self.assertEqual("300", settings.get("CIV6AI_FOCUS_MODEL_IMAGE_SIZE"))

    def test_legacy_name_still_works_and_default(self):
        with mock.patch.dict(os.environ, {"CIV4AI_MAP_IMAGE_CADENCE": "7"}, clear=False):
            os.environ.pop("CIV6AI_MAP_IMAGE_CADENCE", None)
            self.assertEqual("7", settings.get("CIV6AI_MAP_IMAGE_CADENCE", "1"))
        with mock.patch.dict(os.environ, {}, clear=False):
            for name in settings.names("CIV6AI_MAP_IMAGE_CADENCE"):
                os.environ.pop(name, None)
            self.assertEqual("1", settings.get("CIV6AI_MAP_IMAGE_CADENCE", "1"))

    def test_skip_empty_matches_or_chain(self):
        with mock.patch.dict(os.environ, {"CIV5AI_MEMORY_DIR": "/m", "CIV6AI_MEMORY_DIR": ""}, clear=False):
            self.assertEqual("", settings.get("CIV6AI_MEMORY_DIR"))
            self.assertEqual("/m", settings.get("CIV6AI_MEMORY_DIR", skip_empty=True))


if __name__ == "__main__":
    unittest.main()
