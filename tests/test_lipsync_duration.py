import ast, os, subprocess, tempfile, unittest
from pathlib import Path
from test_seedance_aspect_selection import patched_source, ROOT

class TestLipSyncDuration(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  with tempfile.TemporaryDirectory() as td:
   main=Path(td)/'main.py'; main.write_text(patched_source())
   for file in ('main_lipsync_video_provider.patch','main_lipsync_duration.patch'):
    subprocess.run(['patch','--batch','--forward','-p1','-i',str(ROOT/'ops'/file)],cwd=td,check=True,capture_output=True)
   tree=ast.parse(main.read_text())
  names={'_direct_lipsync_duration_sync','_direct_lipsync_fit_audio_sync'}
  funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
  env={'os':os,'tempfile':tempfile,'subprocess':subprocess,'_ffmpeg_exe':lambda:'ffmpeg'}
  exec(compile(ast.fix_missing_locations(ast.Module(body=funcs,type_ignores=[])),'<duration>','exec'),env)
  cls.env=env
 def test_small_overrun_is_fitted_without_cutting_audio(self):
  with tempfile.TemporaryDirectory() as td:
   f=Path(td)/'voice.mp3'
   subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','sine=frequency=500:duration=5.2','-c:a','libmp3lame',str(f)],check=True)
   audio=f.read_bytes()
  probe=self.env['_direct_lipsync_duration_sync']; fit=self.env['_direct_lipsync_fit_audio_sync']
  result=fit(audio,probe(audio,'.mp3'),5.0)
  self.assertGreaterEqual(probe(result,'.mp3'),2.0)
  self.assertLessEqual(probe(result,'.mp3'),4.9)
 def test_excessively_long_audio_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'Сократите текст'):
   self.env['_direct_lipsync_fit_audio_sync'](b'x',12.,5.)
