import asyncio
import unittest
from unittest.mock import AsyncMock

from property_video_director import analyse_reference_photos, parse_photo_analysis


class PropertyVideoDirectorTests(unittest.TestCase):
    def test_analysis_parser_accepts_json_and_rejects_untrusted_prose(self):
        parsed = parse_photo_analysis('{"space":"living_room","summary":"wide living room"}')
        self.assertEqual(parsed["space"], "living_room")
        fallback = parse_photo_analysis("I am not sure")
        self.assertEqual(fallback["space"], "unknown")

    def test_every_reference_is_analysed_with_bounded_concurrency(self):
        active = 0
        peak = 0

        async def analyser(_path, _index):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {"space": "living_room", "summary": "room"}

        result = asyncio.run(analyse_reference_photos([f"{i}.jpg" for i in range(12)], analyser=analyser, concurrency=3))
        self.assertEqual(len(result), 12)
        self.assertLessEqual(peak, 3)


if __name__ == "__main__":
    unittest.main()
