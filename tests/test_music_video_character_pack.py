import ast
from pathlib import Path
import unittest

MAIN = Path(__file__).resolve().parents[1] / "main.py"


class MusicVideoCharacterPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MAIN.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_character_pack_has_four_distinct_roles(self):
        for token in ('"front"', '"three_quarter"', '"full_body"', '"scene"'):
            self.assertIn(token, self.source)
        self.assertIn("Reference 1 is the authoritative frontal face identity", self.source)
        self.assertIn("Reference 4 is the authoritative starting scene/composition", self.source)

    def test_multi_reference_payload_appends_four_images(self):
        fn = next(n for n in self.tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_comet_multi_reference_identity_keyframe")
        text = ast.get_source_segment(self.source, fn)
        self.assertIn("for raw in refs[:4]", text)
        self.assertIn('"inlineData"', text)
        self.assertIn("_prepare_reference_image_for_gemini", text)

    def test_photo_handler_gives_character_pack_priority(self):
        fn = next(n for n in self.tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_photo")
        text = ast.get_source_segment(self.source, fn)
        pack_pos = text.index("_music_video_character_accept_photo")
        studio_pos = text.index("Presentation Studio")
        self.assertLess(pack_pos, studio_pos)

    def test_approval_prefers_synthesized_identity_keyframe(self):
        fn = next(n for n in self.tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_on_music_video_draft_callback")
        text = ast.get_source_segment(self.source, fn)
        self.assertIn('pack.get("keyframe") or _get_cached_photo', text)

    def test_avatar_prompt_has_identity_and_phone_continuity_guard(self):
        fn = next(n for n in self.tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_kling_avatar_result_bytes")
        text = ast.get_source_segment(self.source, fn)
        self.assertIn("IDENTITY LOCK", text)
        self.assertIn("puts it into a pocket", text)
        self.assertIn("Do not morph into another person", text)


if __name__ == "__main__":
    unittest.main()
