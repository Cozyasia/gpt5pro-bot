from pathlib import Path


def test_telegram_file_url_retries_transient_get_file_timeout():
    source = Path("main.py").read_text(encoding="utf-8")
    start = source.index("async def _upload_bytes_to_telegram_file_url")
    end = source.index("\n\nasync def _text_to_public_mp3_url", start)
    fn = source[start:end]

    assert "for attempt in range(3):" in fn
    assert "except TimedOut as exc:" in fn
    assert "await asyncio.sleep(1.5 * (attempt + 1))" in fn
    assert "tg_file = await context.bot.get_file(media.file_id)" in fn
    assert "raise last_exc" in fn
