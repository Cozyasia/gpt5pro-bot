import json, shutil, subprocess, tempfile, unittest
from pathlib import Path
try:
    from neyrobot_prod.continuation_media import source_aspect, join_continuation
except ModuleNotFoundError:
    source_aspect = join_continuation = None

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg required')
class ContinuationMediaTest(unittest.TestCase):
    def make_video(self, path, size, audio):
        cmd=['ffmpeg','-y','-hide_banner','-loglevel','error','-f','lavfi','-i',f'color=c=blue:s={size}:r=12:d=1']
        if audio: cmd+=['-f','lavfi','-i','sine=frequency=440:duration=1']
        cmd+=['-t','1','-c:v','libx264','-threads','1','-pix_fmt','yuv420p']
        if audio: cmd+=['-c:a','aac','-shortest']
        subprocess.run(cmd+[str(path)],check=True)
        return Path(path).read_bytes()
    def test_vertical_input_retains_geometry_duration_and_original_audio(self):
        self.assertIsNotNone(join_continuation)
        with tempfile.TemporaryDirectory() as td:
            src=self.make_video(Path(td)/'a.mp4','90x160',True)
            new=self.make_video(Path(td)/'b.mp4','160x90',False)
            self.assertEqual(source_aspect(src), '9:16')
            out=join_continuation(src,new)
            p=Path(td)/'out.mp4';p.write_bytes(out)
            meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)]))
            video=next(x for x in meta['streams'] if x['codec_type']=='video')
            self.assertEqual((video['width'],video['height']),(90,160))
            self.assertTrue(any(x['codec_type']=='audio' for x in meta['streams']))
            import array
            pcm=subprocess.check_output(['ffmpeg','-v','error','-ss','0.15','-t','0.5','-i',str(p),'-map','0:a:0','-ac','1','-ar','8000','-f','s16le','-'])
            samples=array.array('h',pcm)
            self.assertGreater(sum(abs(x) for x in samples)/max(1,len(samples)), 100, 'original audio must remain audible')
            self.assertGreater(float(meta['format']['duration']),1.8)
    def test_horizontal_and_square_aspects(self):
        self.assertIsNotNone(source_aspect)
        with tempfile.TemporaryDirectory() as td:
            for size, expected in [('160x90','16:9'),('100x100','1:1')]:
                self.assertEqual(source_aspect(self.make_video(Path(td)/(expected.replace(':','_')+'.mp4'),size,False)),expected)

    def test_silent_input_remains_valid_and_invalid_video_fails_closed(self):
        self.assertIsNotNone(join_continuation)
        with tempfile.TemporaryDirectory() as td:
            source=self.make_video(Path(td)/'a.mp4','160x90',False)
            next_video=self.make_video(Path(td)/'b.mp4','160x90',False)
            out=Path(td)/'out.mp4';out.write_bytes(join_continuation(source,next_video))
            metadata=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(out)]))
            self.assertFalse(any(x['codec_type']=='audio' for x in metadata['streams']))
            with self.assertRaises(Exception): source_aspect(b'not a video')
