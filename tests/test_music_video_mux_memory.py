from pathlib import Path

TEXT = Path("main.py").read_text(encoding="utf-8")

def test_file_mux_never_upscales_to_4k_in_web_worker():
    start = TEXT.index("def _mux_video_audio_files_sync")
    end = TEXT.index("def _concat_video_segment_files_sync", start)
    block = TEXT[start:end]
    assert '3840' not in block
    assert '"delivery-4k"' not in block
    assert '"delivery-safe"' in block
    assert 'min(1080' in block

def test_file_mux_remains_file_based():
    start = TEXT.index("def _mux_video_audio_files_sync")
    end = TEXT.index("def _concat_video_segment_files_sync", start)
    block = TEXT[start:end]
    assert "subprocess.run" in block
    assert "TemporaryFile" in block
    assert "stdout=subprocess.DEVNULL" in block
