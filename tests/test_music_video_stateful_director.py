from pathlib import Path
import ast

SRC = Path("main.py").read_text(encoding="utf-8")


def test_stateful_scene_director_is_scene_local():
    tree = ast.parse(SRC)
    names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "_music_video_story_beats" in names
    assert "_vocal_scene_role_prompt" in names
    assert "PRIMARY SUBJECT" in SRC
    assert "REQUIRED ACTION CONTRACT FOR THIS SCENE ONLY" in SRC
    assert "FORBIDDEN TRANSITIONS" in SRC
    assert "do not execute actions belonging to later scenes" in SRC
    assert "supporting character become the protagonist" in SRC


def test_multiscene_identity_is_reanchored_from_real_pack():
    start = SRC.index("async def _start_vocal_clip")
    block = SRC[start:]
    assert "continuity_frame=last_frame" in block
    assert 'refs["face_front"]' in block
    assert 'refs["face_3q"]' in block
    assert 'refs["body_full"]' in block
    assert "Identity + continuity re-anchor" in block


def test_keyframe_synth_accepts_continuity_without_changing_identity_authority():
    start = SRC.index("async def _run_comet_music_video_identity_keyframe")
    end = SRC.index("\n\nasync def _run_comet_ai_selfie_bytes", start)
    block = SRC[start:end]
    assert "continuity_frame: bytes | None = None" in block
    assert '("CONTINUITY_FRAME", continuity_frame)' in block
    assert "repair identity from FACE_FRONT/FACE_3Q" in block
