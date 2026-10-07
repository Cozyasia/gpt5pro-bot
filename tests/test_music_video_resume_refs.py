from pathlib import Path

SRC = Path("main.py").read_text(encoding="utf-8")


def test_approved_audio_resume_loads_identity_pack_before_pending_keyframe_branch():
    start = SRC.index("async def _start_vocal_clip")
    block = SRC[start:start + 18000]
    load = block.index("refs = pack_fn(user_id) if high_fidelity else {}")
    pending = block.index("if high_fidelity and pending_keyframe:")
    reanchor = block.index('refs["face_front"]')
    assert load < pending < reanchor
    assert 'if high_fidelity and not all(refs.get(k)' in block


def test_resume_reanchor_still_uses_all_identity_refs():
    start = SRC.index("async def _start_vocal_clip")
    block = SRC[start:start + 18000]
    assert 'refs["face_front"], refs["face_3q"], refs["body_full"], refs["scene_reference"]' in block
    assert "continuity_frame=last_frame" in block
