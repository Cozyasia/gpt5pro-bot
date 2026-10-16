"""Offline contracts for the user-supplied vocal-track Telegram path."""
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")


class VocalClipCustomAudioFlowTests(unittest.TestCase):
    def test_menu_exposes_a_custom_audio_choice(self):
        self.assertIn('callback_data=f"{base}:vocalclip_audio"', SOURCE)

    def test_audio_is_consumed_before_stt_and_saved_as_the_vocal_source(self):
        marker = 'if context.user_data.get("awaiting_vocal_clip_audio"):'
        self.assertIn(marker, SOURCE)
        self.assertLess(SOURCE.index(marker), SOURCE.index("    # STT"))
        self.assertIn('_save_vocal_artifact, update.effective_user.id, token, "audio", source_audio', SOURCE)
        self.assertIn('"vocal_audio_is_custom"', SOURCE)

    def test_transient_state_clears_the_custom_audio_wait(self):
        self.assertIn('"awaiting_vocal_clip_audio",', SOURCE)


if __name__ == "__main__":
    unittest.main()
