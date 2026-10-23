import os
import unittest
from unittest.mock import patch

from property_video_execution import is_property_video_owner_free


class PropertyVideoOwnerAccessTests(unittest.TestCase):
    def test_owner_is_free_when_gate_is_enabled(self):
        with patch.dict(os.environ, {"OWNER_ID": "123", "PROPERTY_VIDEO_OWNER_FREE_ENABLED": "1"}, clear=False):
            self.assertTrue(is_property_video_owner_free(123))
            self.assertFalse(is_property_video_owner_free(124))

    def test_owner_bypass_can_be_disabled_without_affecting_regular_billing(self):
        with patch.dict(os.environ, {"OWNER_ID": "123", "PROPERTY_VIDEO_OWNER_FREE_ENABLED": "0"}, clear=False):
            self.assertFalse(is_property_video_owner_free(123))


if __name__ == "__main__":
    unittest.main()
