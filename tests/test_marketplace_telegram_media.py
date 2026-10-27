import asyncio
import unittest
from unittest.mock import AsyncMock

from neyrobot_prod.marketplace_generation import GenerationRequest
from neyrobot_prod.marketplace_studio import Output
from neyrobot_prod.marketplace_telegram_media import download_reference_images


class TelegramMediaTests(unittest.TestCase):
    def test_downloads_photos_in_order(self):
        class TelegramFile:
            def __init__(self, payload):
                self.payload = payload

            async def download_to_memory(self, out):
                out.write(self.payload)

        bot = AsyncMock()
        bot.get_file.side_effect = [TelegramFile(b"first"), TelegramFile(b"second")]
        request = GenerationRequest(Output.PHOTOS, "ozon", ("id1", "id2"), "Фарфор")
        result = asyncio.run(download_reference_images(bot, request))
        self.assertEqual([image.content for image in result], [b"first", b"second"])
        self.assertEqual([call.args[0] for call in bot.get_file.await_args_list], ["id1", "id2"])

    def test_rejects_empty_photo(self):
        class EmptyFile:
            async def download_to_memory(self, out):
                return None

        bot = AsyncMock()
        bot.get_file.return_value = EmptyFile()
        request = GenerationRequest(Output.PHOTOS, "ozon", ("id1",), "Фарфор")
        with self.assertRaises(ValueError):
            asyncio.run(download_reference_images(bot, request))


if __name__ == "__main__":
    unittest.main()
