# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

import celebrity_selfie_v141 as v141


class CelebritySelfieV141Tests(unittest.IsolatedAsyncioTestCase):
    def test_version_and_live_contract(self):
        self.assertEqual(v141.VERSION, "v141-accepted-result-targeted-refinement-2026-07-20")
        self.assertIs(v141.v139._repair_weak_side, v141._guarded_auto_repair)
        self.assertIs(v141.v139.selfie.engine._generate, v141._generate)
        self.assertIs(v141.v139.selfie.engine._result_kb, v141._result_kb)

    def test_result_keyboard_has_separate_actions_and_removes_legacy_refine(self):
        markup = v141._result_kb(True)
        rows = markup.inline_keyboard
        texts = [button.text for row in rows for button in row]
        callbacks = [button.callback_data for row in rows for button in row]
        self.assertIn("cs141:similarity", callbacks)
        self.assertIn("cs141:quality", callbacks)
        self.assertIn("cs141:user", callbacks)
        self.assertIn("cs141:celebrity", callbacks)
        self.assertIn("cs141:undo", callbacks)
        self.assertEqual(sum("Улучшить сходство" in text for text in texts), 1)

    def test_snapshot_prefers_fresh_result_over_stale_accepted_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "old.jpg"
            new = Path(tmp) / "new.jpg"
            old.write_bytes(b"old-result")
            new.write_bytes(b"new-result")
            session = {
                "accepted_result_path": str(old),
                "result_path": str(new),
                "scene": "яхта",
                "selected_celebrity_name": "Тест",
            }
            self.assertTrue(v141._snapshot_accepted(session))
            self.assertEqual(session["accepted_result_path"], str(new))
            self.assertEqual(session["accepted_result_sha"], v141._sha(b"new-result"))

    def test_composition_similarity_rejects_a_completely_different_scene(self):
        def image_bytes(value: int) -> bytes:
            from io import BytesIO
            out = BytesIO()
            Image.new("RGB", (600, 800), (value, value, value)).save(out, "JPEG", quality=95)
            return out.getvalue()

        dark = image_bytes(10)
        light = image_bytes(245)
        self.assertGreater(v141._perceptual_similarity(dark, dark), 0.98)
        self.assertLess(v141._perceptual_similarity(dark, light), 0.25)

    def test_local_cleanup_preserves_dimensions(self):
        from io import BytesIO
        image = Image.effect_noise((640, 800), 80).convert("RGB")
        raw = BytesIO()
        image.save(raw, "JPEG", quality=96)
        cleaned = v141._local_cleanup(raw.getvalue())
        with Image.open(BytesIO(cleaned)) as result:
            self.assertEqual(result.size, (640, 800))
        self.assertTrue(cleaned.startswith(b"\xff\xd8\xff"))

    async def test_auto_repair_is_skipped_for_already_good_result(self):
        best = {"identity_min": 75.0, "output": b"same", "total": 80.0}
        with patch.object(v141, "_ORIGINAL_REPAIR_WEAK_SIDE", AsyncMock()) as original:
            result = await v141._guarded_auto_repair(
                object(), best, [b"user"], [b"celebrity"], "Name", "4:5", {}
            )
        self.assertIs(result, best)
        original.assert_not_awaited()
        self.assertEqual(result["auto_repair"], "skipped_above_v141_threshold")

    async def test_identity_safeguard_rejects_scene_replacement(self):
        before = {"user": 70.0, "celebrity": 75.0, "minimum": 70.0, "weighted": 72.0, "unknown": False}
        after = {"user": 90.0, "celebrity": 80.0, "minimum": 80.0, "weighted": 85.0, "unknown": False}
        with patch.object(v141.v140, "_soft_scene_problem", return_value=""), \
             patch.object(v141, "_qc", AsyncMock(return_value=after)), \
             patch.object(v141, "_perceptual_similarity", side_effect=[0.3, 0.4]), \
             patch.object(v141, "_artifact_metrics", return_value={"noise": 2.0, "edge": 20.0, "quality": 90.0}):
            result = await v141._evaluate(
                object(), b"yacht", b"car", b"user", b"celebrity", before,
                action="similarity", side="left", provider="openai",
            )
        self.assertFalse(result["accepted"])
        self.assertIn("scene=0.300", result["reason"])

    def test_source_declares_accepted_result_only_refinement(self):
        source = Path("celebrity_selfie_v141.py").read_text(encoding="utf-8")
        self.assertIn("accepted_result_path", source)
        self.assertIn("raw_selfie_as_refinement_base=disabled", source)
        self.assertIn("Never reuse the reference photo's car", source)
        self.assertIn("CELEBRITY_V141_AUTO_REPAIR_BELOW", source)
        self.assertIn("CELEBRITY_V141_REFINEMENT_PROVIDERS", source)


if __name__ == "__main__":
    unittest.main()
