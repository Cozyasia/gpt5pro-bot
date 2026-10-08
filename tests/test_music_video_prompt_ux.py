from pathlib import Path
import unittest


TEXT = Path("main.py").read_text(encoding="utf-8")
RENDER_BLUEPRINT = Path("render.yaml").read_text(encoding="utf-8")


class MusicVideoPromptUXSourceTests(unittest.TestCase):
    def test_duration_callbacks_are_registered(self):
        self.assertIn("dur10|dur30|dur60|dur90", TEXT)

    def test_render_duration_cap_covers_every_offered_button(self):
        self.assertRegex(
            RENDER_BLUEPRINT,
            r"(?s)- key: PHOTO_CLIP_MAX_DURATION_S\s+value: ['\"]?90['\"]?",
        )

    def test_duration_callback_is_authoritative_and_edits_same_message(self):
        start = TEXT.index('if action in ("dur10", "dur30", "dur60", "dur90")')
        block = TEXT[start:start + 2200]
        self.assertIn('draft["duration"] = seconds', block)
        self.assertIn('draft["duration_locked"] = True', block)
        self.assertIn("_music_video_replace_duration_field(video_brief, seconds)", block)
        self.assertIn("edit_text", block)
        self.assertNotIn("reply_text(_music_video_review_text", block)

    def test_approval_passes_selected_duration_to_provider(self):
        start = TEXT.index('if action != "approve"')
        block = TEXT[start:start + 5200]
        self.assertIn('seconds = int(draft.get("duration")', block)
        self.assertIn("target_duration_s=seconds", block)

    def test_prompt_assistant_buttons_exist(self):
        self.assertIn("✨ Сделать промпт автоматически", TEXT)
        self.assertIn("🎙 По голосовому описанию", TEXT)
        self.assertIn('action == "auto"', TEXT)
        self.assertIn('action == "voice"', TEXT)
        self.assertIn('"voice_rewrite"', TEXT)

    def test_duration_replacement_is_line_scoped(self):
        start = TEXT.index("def _music_video_replace_duration_field")
        helper = TEXT[start:TEXT.index("async def _stage_music_video_draft", start)]
        self.assertIn('r"(?im)^\\s*', helper)
        self.assertIn("minutes?", helper)
        self.assertIn("мин\\w*", helper)
        self.assertNotIn('re.sub(r"\\b', helper)


if __name__ == "__main__":
    unittest.main()
