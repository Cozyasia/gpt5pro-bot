from pathlib import Path


SOURCE = Path("main.py").read_text(encoding="utf-8")


def test_music_video_telegram_artifact_upload_retries_send_and_get_file():
    start = SOURCE.index("async def _upload_bytes_to_telegram_file_url")
    end = SOURCE.index("\n\nasync def _text_to_public_mp3_url", start)
    fn = SOURCE[start:end]
    assert fn.count("for attempt in range(3):") >= 2
    assert "telegram reply_document timeout" in fn
    assert "telegram get_file timeout" in fn
    assert "read_timeout=60" in fn
    assert "write_timeout=60" in fn
    assert "bio = BytesIO(raw)" in fn
    assert fn.index("for attempt in range(3):") < fn.index("bio = BytesIO(raw)")


def test_music_video_background_job_has_progress_heartbeat_and_cleanup():
    start = SOURCE.index("async def _start_vocal_clip")
    end = SOURCE.index("\n\nasync def _start_text_video", start)
    fn = SOURCE[start:end]
    assert "timeout=150" in fn
    assert "Работа продолжается, бот не завис" in fn
    assert "heartbeat_stop.set()" in fn
    assert "heartbeat_task.cancel()" in fn
    assert "await heartbeat_task" in fn
