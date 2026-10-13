"""No-charge regression tests for the durable 24-second Veo workflow."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Veo24SecondProductionFlowTests(unittest.TestCase):
    def test_telegram_callback_accepts_24_seconds(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('pattern=r"^veoopt:dur:(?:8|15|24|30|60)$"', source)

    def test_voice_fit_rejects_a_speed_change_outside_safe_limit(self):
        from neyrobot_prod.veo_tts_timeline import required_atempo_factor

        self.assertAlmostEqual(required_atempo_factor(24.0), 1.0)
        with self.assertRaisesRegex(ValueError, "10%"):
            required_atempo_factor(20.0)

    def test_lipsync_state_blocks_resubmit_after_unknown_submission(self):
        from neyrobot_prod.veo_24s_state import (
            begin_lipsync_submission,
            load_state,
            mark_lipsync_uncertain,
        )

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "workflow.json"
            begin_lipsync_submission(state_path, 1)
            mark_lipsync_uncertain(state_path, 1)
            with self.assertRaisesRegex(RuntimeError, "reconciliation"):
                begin_lipsync_submission(state_path, 1)
            self.assertEqual(load_state(state_path)["lipsync"]["1"]["state"], "uncertain")

    def test_final_assembler_does_not_fade_between_lipsynced_scenes(self):
        source = (ROOT / "neyrobot_prod" / "veo_assembler.py").read_text(encoding="utf-8")
        self.assertNotIn("fade=t=in", source)
        self.assertNotIn("afade=t=in", source)

    def test_main_wires_master_tts_lipsync_and_final_mux(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        start = source.index("async def _run_veo_24s_lipsync")
        end = source.index("\n\nasync def cmd_veo_recover", start)
        workflow = source[start:end]
        for required in (
            "_tts_bytes_sync", "fit_tts_master_to_24_seconds", "split_tts_master",
            "resume_veo_job", "assemble_vertical_video", "mux_master_voice",
            "_apply_kling_lipsync_to_scene_file", "mark_lipsync_accepted",
            "mark_lipsync_completed", "mark_lipsync_uncertain",
        ):
            self.assertIn(required, workflow)
        self.assertIn("assemble=False", workflow)

    def test_24s_billing_includes_veo_tts_and_three_lipsync_jobs(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("VEO_24S_KLING_LIPSYNC_COST_USD", source)
        self.assertIn("VEO_24S_TTS_COST_PER_MINUTE_USD", source)
        self.assertIn("def _veo_24s_provider_cost_usd", source)
        self.assertIn("3 * VEO_24S_KLING_LIPSYNC_COST_USD", source)
        self.assertIn("provider_cost = _veo_24s_provider_cost_usd() if engine == \"veo\" and duration == 24", source)


if __name__ == "__main__":
    unittest.main()
