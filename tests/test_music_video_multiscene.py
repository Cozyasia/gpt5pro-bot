from pathlib import Path
import ast

SRC = Path(__file__).resolve().parents[1] / "main.py"
TEXT = SRC.read_text(encoding="utf-8")


def test_multiscene_source_parses():
    ast.parse(TEXT)


def test_duration_selector_offers_10_30_60_90():
    for action in ("dur10", "dur30", "dur60", "dur90"):
        assert f"mv:{action}:" in TEXT
    assert 'seconds = int(action[3:])' in TEXT


def test_long_vocal_clip_is_not_blocked_at_approval_or_start():
    assert "Пока доступно до 10 секунд" not in TEXT
    assert "Вокальный клип на {target_duration} секунд пока недоступен" not in TEXT
    start = TEXT.index("async def _start_vocal_clip")
    block = TEXT[start:TEXT.index("\nasync def ", start + 40)]
    assert "scene_count = max(1, min(PHOTO_CLIP_MAX_SCENES" in block


def test_duration_is_video_parameter_not_suno_brief():
    cb = TEXT[TEXT.index("async def _on_music_video_draft_callback"):TEXT.index("def _photoclip_preset_prompt")]
    assert "music_brief, video_brief = _music_video_split_briefs" in cb
    assert 'draft["prompt"] = _music_video_join_briefs(music_brief, video_brief)' in cb


def test_multiscene_prompt_is_generic_and_chronological():
    fn = TEXT[TEXT.index("def _vocal_scene_role_prompt"):TEXT.index("async def _extract_audio_segment_bytes")]
    assert "execute only the chronological" in fn
    assert "do not restart the story" in fn
    assert "Preserve spatial direction" in fn
    assert "If doors must open" not in fn
    assert "Do not dance" not in fn


def test_multiscene_uses_previous_last_frame_for_continuity():
    assert "def _extract_last_video_frame_sync" in TEXT
    start = TEXT.index("async def _start_vocal_clip")
    block = TEXT[start:TEXT.index("\nasync def ", start + 40)]
    assert "continuation_bytes, continuation_url = img_bytes, keyframe_url" in block
    assert "_extract_last_video_frame_sync, scene_video" in block
    assert "continuation_bytes = last_frame" in block
    assert 'continuation_url = await _upload_bytes_to_telegram_file_url(' in block
    assert "continuation_bytes, scene_prompt, dur_s, aspect, continuation_url" in block


def test_identity_lock_survives_each_segment():
    start = TEXT.index("async def _start_vocal_clip")
    block = TEXT[start:TEXT.index("\nasync def ", start + 40)]
    assert "IDENTITY LOCK" in block
    assert "match the Character Identity Pack person, not a lookalike" in block
    assert "continuation frame controls pose/action continuity" in block


class TestMemorySafeFinalize(unittest.TestCase):
    def test_long_finalize_spills_segments_and_muxes_files(self):
        src = pathlib.Path("main.py").read_text(encoding="utf-8")
        self.assertIn("def _mux_video_audio_files_sync", src)
        self.assertIn("def _concat_video_segment_files_sync", src)
        self.assertIn("segments.clear()", src)
        self.assertIn("subprocess.DEVNULL", src)
        self.assertIn("source_size <= max_bytes", src)
        block = src[src.index('await update.effective_message.reply_text("🎬 Собираю итоговый cinematic видеоряд…")'):]
        self.assertIn("_mux_video_audio_files_sync", block)
        self.assertNotIn("_mux_video_audio_sync, joined, safe_audio", block[:5000])
