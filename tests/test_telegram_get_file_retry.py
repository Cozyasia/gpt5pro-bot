from pathlib import Path
import unittest


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


class IncomingTelegramFileRetryTests(unittest.TestCase):
    def test_incoming_photo_uses_retry_helper(self):
        source = Path("main.py").read_text(encoding="utf-8")
        helper_start = source.index("async def _telegram_media_get_file_with_retry")
        helper_end = source.index("\n\nasync def _upload_bytes_to_telegram_file_url", helper_start)
        helper = source[helper_start:helper_end]
        photo_start = source.index("async def on_photo")
        photo_end = source.index("\nasync def on_voice", photo_start)
        photo = source[photo_start:photo_end]
        self.assertIn("for attempt in range(3):", helper)
        self.assertIn("except TimedOut as exc:", helper)
        self.assertIn("await _telegram_media_get_file_with_retry(ph", photo)
