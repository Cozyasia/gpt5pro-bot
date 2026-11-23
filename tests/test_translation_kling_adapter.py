import unittest
from unittest.mock import AsyncMock
from neyrobot_prod.translation_segments import kling_sync_segment

class KlingAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_two_separate_media_inputs_and_duration(self):
        calls=[]
        def publish(content,name):
            calls.append((content,name))
            return 'https://example.test/'+name
        provider=AsyncMock(return_value=b'video result')
        result=await kling_sync_segment(b'video',b'audio',5500,publish,provider)
        self.assertEqual(result,b'video result')
        self.assertEqual(calls,[(b'video','translation_video.mp4'),(b'audio','translation_audio.mp3')])
        provider.assert_awaited_once_with('https://example.test/translation_video.mp4','https://example.test/translation_audio.mp3',duration_ms=5500)

    async def test_provider_errors_are_propagated_without_retry(self):
        provider=AsyncMock(side_effect=RuntimeError('provider unavailable'))
        with self.assertRaisesRegex(RuntimeError,'provider unavailable'):
            await kling_sync_segment(b'video',b'audio',5000,lambda data,name:'https://example.test/'+name,provider)
        self.assertEqual(provider.await_count,1)
