import unittest
from neyrobot_prod.translation_segments import plan_segments

class TranslationSegmentTests(unittest.TestCase):
    def test_lengths_cover_video_without_gaps(self):
        for duration in (2, 9.9, 10, 10.1, 11, 21, 59.7, 180):
            spans = plan_segments(duration)
            self.assertAlmostEqual(spans[0][0], 0)
            self.assertAlmostEqual(spans[-1][1], duration)
            for start, end in spans:
                self.assertGreaterEqual(end-start, 2)
                self.assertLessEqual(end-start, 10)
            for a,b in zip(spans,spans[1:]):
                self.assertAlmostEqual(a[1],b[0])

    def test_invalid_durations(self):
        for duration in (0,1.99,180.1,float('nan'),float('inf')):
            with self.assertRaises(ValueError): plan_segments(duration)

class VideoTranslationPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_splits_syncs_and_reassembles_with_audio(self):
        import asyncio, subprocess, tempfile, json
        from pathlib import Path
        from neyrobot_prod.translation_segments import sync_translated_video
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'source.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10','-f','lavfi','-i','sine=frequency=600','-t','11','-c:v','libx264','-preset','ultrafast','-c:a','aac',str(source)],check=True)
            calls=[]
            async def provider(video,audio,duration_ms):
                self.assertGreater(len(video),1000)
                self.assertGreater(len(audio),1000)
                calls.append(duration_ms)
                return video
            result=await sync_translated_video(source.read_bytes(),11,provider)
            self.assertEqual(len(calls),2)
            self.assertEqual(sum(calls),11000)
            out=Path(td)/'out.mp4';out.write_bytes(result)
            meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(out)]))
            self.assertTrue(any(s['codec_type']=='audio' for s in meta['streams']))
            self.assertAlmostEqual(float(meta['format']['duration']),11,delta=0.25)

    async def test_provider_failure_is_not_silently_ignored(self):
        from neyrobot_prod.translation_segments import sync_translated_video
        async def provider(video,audio,duration_ms): raise RuntimeError('provider failed')
        import subprocess,tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'source.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10','-f','lavfi','-i','sine=frequency=600','-t','3','-c:v','libx264','-preset','ultrafast','-c:a','aac',str(f)],check=True)
            with self.assertRaisesRegex(RuntimeError,'provider failed'):
                await sync_translated_video(f.read_bytes(),3,provider)

    async def test_truncated_provider_video_is_rejected(self):
        import subprocess,tempfile
        from pathlib import Path
        from neyrobot_prod.translation_segments import sync_translated_video
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'source.mp4'; short=Path(td)/'short.mp4'
            for path,duration in ((source,'5'),(short,'2')):
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10','-f','lavfi','-i','sine=frequency=600','-t',duration,'-c:v','libx264','-preset','ultrafast','-c:a','aac',str(path)],check=True)
            async def provider(video,audio,duration_ms): return short.read_bytes()
            with self.assertRaisesRegex(RuntimeError,'duration'):
                await sync_translated_video(source.read_bytes(),5,provider)
