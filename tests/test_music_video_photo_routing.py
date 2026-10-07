from pathlib import Path

SRC = Path("main.py").read_text(encoding="utf-8")


def test_custom_scenario_does_not_alias_last_photo():
    assert 'if data == "act:fun:photoclip_last":' in SRC
    assert 'if data == "act:fun:photoclip_custom":' in SRC
    assert 'if action == "photoclip_last":' in SRC
    assert 'if action == "photoclip_custom":' in SRC
    assert "Сначала соберём Character Identity Pack" in SRC


def test_photo_handler_recovers_missing_identity_wait_state():
    start = SRC.index("async def on_photo")
    block = SRC[start:start + 9000]
    assert '_mode_track_get(user_id) == "photoclip"' in block
    assert "not _music_video_identity_complete(user_id)" in block
    assert '("face_front", "face_3q", "body_full", "scene_reference")' in block
    assert "_set_music_video_identity_wait(context, identity_slot)" in block
