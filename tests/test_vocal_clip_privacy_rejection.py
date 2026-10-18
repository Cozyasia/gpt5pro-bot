from pathlib import Path
import unittest


SOURCE = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")


def _block(function_name: str) -> str:
    start = SOURCE.index(f"def {function_name}")
    end = SOURCE.find("\n\ndef ", start + 5)
    return SOURCE[start:] if end < 0 else SOURCE[start:end]


class VocalClipPrivacyRejectionTests(unittest.TestCase):
    def test_privacy_rejection_does_not_offer_a_useless_same_portrait_resume(self):
        block = _block("_vocal_song_kb")
        self.assertIn("privacy_rejected", block)
        self.assertIn("Загрузить другой портрет", block)
        self.assertIn("if resume and not privacy_rejected", block)

    def test_user_receives_the_provider_reason_and_keeps_the_song(self):
        block = SOURCE[SOURCE.index("async def _start_vocal_clip"):SOURCE.index("async def _run_kling_text_shorts")]
        self.assertIn("_is_seedance_privacy_rejection", block)
        self.assertIn("Seedance отклонил входной кадр", block)
        self.assertIn("privacy_rejected=privacy_rejected", block)


if __name__ == "__main__":
    unittest.main()
