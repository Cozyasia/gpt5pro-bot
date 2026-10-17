from pathlib import Path
import unittest


SOURCE = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")


def _block(function_name: str) -> str:
    start = SOURCE.index(f"async def {function_name}")
    end = SOURCE.find("\nasync def ", start + 20)
    return SOURCE[start:] if end < 0 else SOURCE[start:end]


class VocalClipUiFlowTests(unittest.TestCase):
    def test_portrait_upload_retires_the_selector_and_waits_for_photo_only(self):
        block = _block("_handle_vocalclip_upload_choice")
        self.assertIn('context.user_data["vocal_clip_flow"] = True', block)
        self.assertIn("edit_reply_markup(reply_markup=None)", block)
        self.assertNotIn("reply_markup=_vocal_clip_action_kb", block)
        self.assertIn("Пришлите фронтальный портрет", block)

    def test_vocal_mode_flag_is_preserved_into_the_approved_draft(self):
        stage = _block("_stage_music_video_draft")
        approve = _block("_on_music_video_draft_callback")
        self.assertIn('"force_vocal_lipsync"', stage)
        self.assertIn('draft.get("force_vocal_lipsync")', approve)

    def test_vocal_result_is_normalized_to_vertical_before_original_audio_is_muxed(self):
        pipeline = _block("_start_vocal_clip")
        normalize_at = pipeline.index("_normalize_vocal_clip_vertical_file_sync")
        mux_at = pipeline.index("_mux_video_audio_files_sync")
        self.assertLess(normalize_at, mux_at)
