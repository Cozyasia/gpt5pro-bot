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


def test_music_video_audio_approval_and_fidelity_contracts():
    source = MAIN.read_text(encoding="utf-8")
    assert "FOLLOW THESE SONG REQUIREMENTS STRICTLY" in source
    assert '"make_instrumental": instrumental' in source
    assert "ABSOLUTE authority for the person's CURRENT FACE" in source
    assert "THIS IS A NARRATIVE ACTION SHOT, NOT A DANCE OR PERFORMANCE SHOT" in source
    assert "Подтвердить это аудио" in source
    assert "Сгенерировать другое аудио" in source
    assert "_vocal_song_kb(song_token, pending=True)" in source
    assert "Видео ещё НЕ запускаю" in source
    assert "with contextlib.suppress(BadRequest):" in source


def test_suno_intro_does_not_force_whole_track_instrumental_and_review_callbacks_route():
    source = MAIN.read_text(encoding="utf-8")
    assert "intro_only = bool(re.search" in source
    assert "instrumental = (not intro_only)" in source
    assert 'pattern=r"^mvfile:(?:audio|use|video|approveaudio|regenaudio):[0-9a-f]{12}$"' in source
    assert 'context.user_data["music_video_pending_music_brief"] = music_brief' in source
    assert "fresh = await _run_suno_music_result_bytes(update, brief)" in source
    assert "return False" in source


def test_music_video_suno_matches_proven_freeform_inspiration_payload():
    source = MAIN.read_text(encoding="utf-8")
    fn = source[source.index("async def _run_suno_music_result_bytes"):source.index("async def _send_vocal_song_file")]
    assert 'base_payload = {"mv": SUNO_MODEL, "gpt_description_prompt": brief}' in fn
    assert '"gpt_description_prompt": strict_brief' not in fn
    assert 'base_payload.update({"prompt": "", "make_instrumental": True})' in fn
    assert '"make_instrumental": instrumental' not in fn

def test_kling_receives_literal_action_before_generic_constraints():
    source = MAIN.read_text(encoding="utf-8")
    photo = source[source.index("def _photo_clip_prompt"):source.index("def _photo_clip_target_duration")]
    assert "USER ACTION/DIRECTOR DIRECTION" in photo
    assert "user_prompt[:2200]" in photo
    scene = source[source.index("def _vocal_scene_role_prompt"):source.index("async def _extract_audio_segment_bytes")]
    assert scene.index("MANDATORY USER VIDEO DIRECTION") < scene.index("THIS IS A NARRATIVE ACTION SHOT")

def test_audio_review_rejects_stale_tokens_and_regenerate_replaces_pending_token():
    source = MAIN.read_text(encoding="utf-8")
    assert 'pending_token = context.user_data.get("music_video_pending_audio_token")' in source
    assert 'if pending_token != token:' in source
    assert 'context.user_data["music_video_pending_audio_token"] = new_token' in source
    assert 'context.user_data.pop("vocal_source_token", None)' in source


def test_keyframe_action_priming_is_scenario_agnostic():
    source = MAIN.read_text(encoding="utf-8")
    fn = source[source.index("async def _run_comet_music_video_identity_keyframe"):source.index("async def _start_vocal_clip")]
    assert "FIRST ACTIONABLE STATE" in fn
    assert "pose, held object, gaze direction, body orientation" in fn
    assert "Do not invent scenario-specific actions or props" in fn
    assert "phone already being lowered" not in fn
    assert "elevator doors already opening" not in fn


def test_kling_prompt_is_guarded_below_provider_2500_character_limit():
    source = MAIN.read_text(encoding="utf-8")
    fn = source[source.index("async def _run_kling_photo_clip_result"):source.index("async def _run_suno_music_result_bytes")]
    assert "if len(kling_prompt) > 2480:" in fn
    assert 'kling_prompt = kling_prompt[:2476].rstrip() + "..."' in fn
    assert '"prompt": kling_prompt' in fn

def test_audio_review_can_edit_prompt_without_starting_video():
    source = MAIN.read_text(encoding="utf-8")
    assert "✏️ Изменить промпт аудио" in source
    assert "mvfile:editaudio:" in source
    assert '"awaiting_music_video_audio_prompt_edit"' in source
    assert 'context.user_data["music_video_pending_music_brief"] = new_brief' in source
    assert '_music_video_join_briefs(new_brief, pending_video)' in source
