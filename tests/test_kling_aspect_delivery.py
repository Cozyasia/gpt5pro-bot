import json, subprocess, tempfile, unittest
from pathlib import Path
from neyrobot_prod.kling_aspect_delivery import normalize_kling_video

class AspectDeliveryTest(unittest.TestCase):
    def sample(self, directory, size='320x240'):
        path=Path(directory)/'source.mp4'
        subprocess.run(['ffmpeg','-y','-loglevel','error','-f','lavfi','-i',f'color=c=blue:s={size}:r=10:d=0.6','-f','lavfi','-i','sine=frequency=440:duration=0.6','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(path)],check=True)
        return path.read_bytes()
    def probe(self, video, directory):
        p=Path(directory)/'output.mp4';p.write_bytes(video)
        return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=codec_type,width,height','-of','json',str(p)]))['streams']
    def test_format_and_audio(self):
        for aspect, dimensions in [('9:16',(720,1280)),('16:9',(1280,720)),('1:1',(720,720))]:
            with self.subTest(aspect=aspect), tempfile.TemporaryDirectory() as d:
                result, changed=normalize_kling_video(self.sample(d),aspect)
                streams=self.probe(result,d); v=next(s for s in streams if s['codec_type']=='video')
                self.assertEqual((v['width'],v['height']),dimensions)
                self.assertTrue(any(s['codec_type']=='audio' for s in streams))
                self.assertTrue(changed)
    def test_already_matching_is_identical(self):
        with tempfile.TemporaryDirectory() as d:
            original=self.sample(d,'180x320')
            result, changed=normalize_kling_video(original,'9:16')
            self.assertFalse(changed);self.assertEqual(original,result)
    def test_bad_content_and_aspect_fail(self):
        with self.assertRaises(ValueError): normalize_kling_video(b'bad','9:16')
        with self.assertRaises(ValueError): normalize_kling_video(b'bad','3:2')
