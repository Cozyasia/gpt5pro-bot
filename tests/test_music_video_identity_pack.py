from pathlib import Path
import ast

SRC = Path(__file__).resolve().parents[1] / "main.py"
TEXT = SRC.read_text(encoding="utf-8")


def test_main_parses():
    ast.parse(TEXT)


def test_identity_pack_has_four_isolated_slots():
    for token in ("face_front", "face_3q", "body_full", "scene_reference"):
        assert token in TEXT
    assert "_music_video_identity_cache" in TEXT
    assert "_music_video_identity_complete" in TEXT


def test_gemini_identity_synthesis_really_sends_four_images():
    start = TEXT.index("async def _run_comet_music_video_identity_keyframe")
    end = TEXT.index("async def _run_comet_ai_selfie_bytes", start)
    block = TEXT[start:end]
    assert '("FACE_FRONT", face_front)' in block
    assert '("FACE_3Q", face_3q)' in block
    assert '("BODY_FULL", body_full)' in block
    assert '("SCENE_REFERENCE", scene_reference)' in block
    assert '"inlineData"' in block
    assert '"parts": parts' in block


def test_vocal_action_path_uses_synthesized_keyframe_and_not_avatar():
    start = TEXT.index("async def _start_vocal_clip")
    end = TEXT.index("\nasync def ", start + 30)
    block = TEXT[start:end]
    assert "_run_comet_music_video_identity_keyframe(" in block
    assert "img_bytes = keyframe" in block
    assert "if high_fidelity:" in block
    assert "_run_kling_photo_clip_result(" in block
    assert "keyframe_url = await _upload_bytes_to_telegram_file_url(" in block
    assert 'if not keyframe_url.startswith("https://")' in block
    assert "img_bytes, scene_prompt, dur_s, aspect, keyframe_url" in block
    assert "Compatibility only for isolated legacy unit-test harnesses" in block
    assert "vocal_start is not reliably detected yet" in block


def test_phone_action_is_physical_not_magic_removal():
    assert "lowers the phone, puts it into a pocket" in TEXT
    assert "the phone never appears again" in TEXT


def test_review_timestamps_are_seconds_not_fake_minutes():
    start = TEXT.index("def _music_video_director_plan")
    end = TEXT.index("def _music_video_review_text", start)
    block = TEXT[start:end]
    assert 'f"0:{a:02d}–0:{b:02d}' in block
    assert 'f"{a:02d}:00–{b:02d}:00' not in block


def test_song_video_hard_route_preserved():
    assert 'return "video"' in TEXT
    assert 'return "music"' in TEXT
    assert "awaiting_music_video_video_brief" in TEXT
    assert "VIDEO_BRIEF consumes here and never re-enters generic on_text intent routing." in TEXT
