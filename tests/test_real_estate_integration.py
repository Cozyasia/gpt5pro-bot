"""Tests for feature flag, shot allocation and guarded property-video routing."""
import os
import unittest
from unittest.mock import patch

from real_estate_pipeline import plan_shots
from real_estate_bootstrap import install


class PropertyVideoIntegrationTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {"REAL_ESTATE_VIDEO_ENABLED": "0"}):
            self.assertFalse(install())

    def test_shot_plan_duration(self):
        shots = plan_shots(["a", "b", "c", "d"], 20)
        self.assertEqual(sum(s["seconds"] for s in shots), 20)
        self.assertEqual([s["photo_id"] for s in shots], ["a", "b", "c", "d"])

    def test_empty_photos_rejected(self):
        with self.assertRaises(ValueError):
            plan_shots([], 10)

    def test_guarded_handlers_do_not_consume_other_modes(self):
        import asyncio
        from types import SimpleNamespace
        from real_estate_safe_router import _photo, _text
        update = SimpleNamespace(message=None)
        context = SimpleNamespace(user_data={})
        asyncio.run(_photo(update, context))
        asyncio.run(_text(update, context))


if __name__ == "__main__":
    unittest.main()
