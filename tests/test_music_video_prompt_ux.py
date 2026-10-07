from pathlib import Path

TEXT = Path("main.py").read_text(encoding="utf-8")

def test_duration_callbacks_are_registered():
    assert "dur10|dur30|dur60|dur90" in TEXT

def test_duration_callback_is_authoritative_and_edits_same_message():
    start = TEXT.index('if action in ("dur10", "dur30", "dur60", "dur90")')
    block = TEXT[start:start + 1900]
    assert 'draft["duration"] = seconds' in block
    assert 'r"\\b(?:длительность' in block
    assert 'r"\\\\b' not in block
    assert "edit_text" in block
    assert "reply_text(_music_video_review_text" not in block

def test_approval_canonicalizes_selected_duration():
    start = TEXT.index('if action != "approve"')
    block = TEXT[start:start + 3800]
    assert 'seconds = int(draft.get("duration")' in block
    assert 'Длительность клипа: {seconds} секунд' in block

def test_prompt_assistant_buttons_exist():
    assert "✨ Сделать промпт автоматически" in TEXT
    assert "🎙 По голосовому описанию" in TEXT
    assert 'action == "auto"' in TEXT
    assert 'action == "voice"' in TEXT
    assert '"voice_rewrite"' in TEXT
