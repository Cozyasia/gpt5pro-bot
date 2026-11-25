import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from neyrobot_prod import translation_public_flow as flow
from neyrobot_prod.translation_paid_service import make_quote

PRICES = dict(identify_per_segment=.01, lipsync_per_segment=.08,
              transcription=.01, translation=.01, speech=.01)

class PublicTranslationFlowTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.db=str(Path(self.tmp.name)/'subs.db')
  with sqlite3.connect(self.db) as db:
   db.executescript('''CREATE TABLE wallet(user_id INTEGER PRIMARY KEY, usd REAL);
    INSERT INTO wallet VALUES(1, 10);
    CREATE TABLE credit_ledger(tx_id TEXT PRIMARY KEY,user_id INTEGER,feature TEXT,
      engine TEXT,provider_cost_usd REAL,retail_usd REAL,credits REAL,status TEXT,
      metadata_json TEXT,created_ts INTEGER,updated_ts INTEGER);''')
  self.events=[]
 async def asyncTearDown(self): self.tmp.cleanup()
 def wallet(self):
  with sqlite3.connect(self.db) as db:
   return db.execute('SELECT usd FROM wallet').fetchone()[0], db.execute('SELECT status FROM credit_ledger').fetchone()[0]
 def args(self):
  async def dubbed(video,duration,language):
   self.events.append(('dub',language)); return b'dubbed'
  def publish(data,name): return 'https://files.example/'+name
  async def kling(video,audio,*,duration_ms,on_provider_state):
   self.events.append(('kling',duration_ms));on_provider_state('identify_session_id','session')
   on_provider_state('lip_sync_task_id','task-1');return b'provider video'
  async def deliver(video): self.events.append(('deliver',video));return True
  return dict(db_path=self.db,request_id='chat:123:message:45',user_id=1,source_video=b'source',duration=5,language='English',quote=make_quote(5,pricing=PRICES,retail_quote=lambda cost:(.5,50)),transcribe_and_dub=dubbed,publish=publish,kling=kling,deliver=deliver)
 async def test_success_and_repeated_update_charged_once(self):
  async def sync(video,duration,segment):
   self.assertEqual(video,b'dubbed');return await segment(b'clip',b'audio',5000)
  args=self.args()
  with patch.object(flow,'sync_translated_video',sync):
   first=await flow.run_short_translation(**args);second=await flow.run_short_translation(**args)
  self.assertEqual((first.state,second.state),('delivered','already_started'))
  self.assertEqual(self.wallet(),(9.5,'charged'))
  self.assertEqual(self.events,[('dub','English'),('kling',5000),('deliver',b'provider video')])
 async def test_no_provider_task_means_no_delivery_or_charge(self):
  args=self.args()
  async def kling(*args,**kwargs):return b'video'
  args['kling']=kling
  async def sync(video,duration,segment):return await segment(b'clip',b'audio',5000)
  with patch.object(flow,'sync_translated_video',sync):
   self.assertEqual((await flow.run_short_translation(**args)).state,'unknown')
  self.assertEqual(self.wallet(),(10,'reserved'))
  self.assertFalse(any(e[0]=='deliver' for e in self.events))
 async def test_invalid_or_missing_price_never_launches(self):
  args=self.args();args['quote']=None
  with self.assertRaises(ValueError):await flow.run_short_translation(**args)
  self.assertEqual(self.events,[])
 async def test_unsupported_duration_does_not_touch_wallet(self):
  args=self.args();args['duration']=11
  with self.assertRaises(ValueError):await flow.run_short_translation(**args)
  self.assertEqual(self.events,[])
 async def test_real_media_pipeline_with_simulated_provider_and_wallet(self):
  import json, subprocess
  source=Path(self.tmp.name)/'source.mp4'
  subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10',
    '-f','lavfi','-i','sine=frequency=600','-t','3','-c:v','libx264','-preset','ultrafast',
    '-c:a','aac',str(source)],check=True)
  source_bytes=source.read_bytes(); files={}; delivered=[]
  args=self.args();args.update(source_video=source_bytes,duration=3,
   quote=make_quote(3,pricing=PRICES,retail_quote=lambda cost:(.5,50)))
  async def dub(video,duration,language):return video
  def publish(data,name):
   files[name]=data; return 'https://files.example/'+name
  async def kling(video,audio,*,duration_ms,on_provider_state):
   on_provider_state('lip_sync_task_id','media-task');return files['translation_video.mp4']
  async def deliver(video):delivered.append(video);return True
  args.update(transcribe_and_dub=dub,publish=publish,kling=kling,deliver=deliver)
  result=await flow.run_short_translation(**args)
  self.assertEqual(result.state,'delivered');self.assertEqual(self.wallet(),(9.5,'charged'))
  output=Path(self.tmp.name)/'result.mp4';output.write_bytes(delivered[0])
  info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(output)]))
  self.assertTrue(any(s['codec_type']=='audio' for s in info['streams']))
  self.assertAlmostEqual(float(info['format']['duration']),3,delta=.25)
