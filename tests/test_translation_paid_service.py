import sqlite3,tempfile,unittest
from pathlib import Path
try:
 from neyrobot_prod import translation_paid_service as service
except ImportError:
 service=None

class TranslationPaidServiceTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=str(Path(self.tmp.name)/'db.sqlite')
  with sqlite3.connect(self.db) as c:c.executescript('''CREATE TABLE wallet(user_id INTEGER PRIMARY KEY,usd REAL); INSERT INTO wallet VALUES(1,10); CREATE TABLE credit_ledger(tx_id TEXT PRIMARY KEY,user_id INTEGER,feature TEXT,engine TEXT,provider_cost_usd REAL,retail_usd REAL,credits REAL,status TEXT,metadata_json TEXT,created_ts INTEGER,updated_ts INTEGER);''')
 async def asyncTearDown(self):self.tmp.cleanup()
 def pricing(self):return dict(identify_per_segment='.007',lipsync_per_segment='.07',transcription='.01',translation='.01',speech='.01')
 async def test_quotes_all_steps_and_charges_after_delivery(self):
  self.assertIsNotNone(service)
  seen=[]
  async def render(on_task):on_task('task-1');return b'video'
  async def deliver(video):seen.append(video);return True
  result=await service.run(self.db,'request',1,5,pricing=self.pricing(),retail_quote=lambda cost:(float(cost)*1.25,20),render=render,deliver=deliver)
  self.assertEqual(result.state,'delivered');self.assertAlmostEqual(result.provider_cost,.107);self.assertEqual(seen,[b'video'])
  with sqlite3.connect(self.db) as c:
   self.assertAlmostEqual(c.execute('SELECT usd FROM wallet').fetchone()[0],10-.107*1.25)
 async def test_missing_pricing_fails_before_any_provider_call(self):
  self.assertIsNotNone(service)
  calls=[]
  async def render(cb):calls.append('render');return b'x'
  async def deliver(v):calls.append('send');return True
  p=self.pricing();p['speech']=None
  with self.assertRaises(ValueError):await service.run(self.db,'req',1,5,pricing=p,retail_quote=lambda c:(1,20),render=render,deliver=deliver)
  self.assertEqual(calls,[])
 async def test_invalid_retail_quote_does_not_start_provider(self):
  self.assertIsNotNone(service)
  async def render(cb):self.fail('provider must not be started')
  async def deliver(v):self.fail('delivery must not start')
  with self.assertRaises(ValueError):await service.run(self.db,'req',1,5,pricing=self.pricing(),retail_quote=lambda c:(float('nan'),20),render=render,deliver=deliver)
 async def test_confirmed_quote_is_not_recalculated(self):
  quote=service.make_quote(5,pricing=self.pricing(),retail_quote=lambda cost:(.5,50))
  async def render(cb):cb('quoted-task');return b'video'
  async def deliver(video):return True
  result=await service.run_quoted(self.db,'quoted-request',1,quote,render=render,deliver=deliver)
  self.assertEqual((result.retail_cost,result.credits),(.5,50))
  with sqlite3.connect(self.db) as db:
   self.assertEqual(db.execute('SELECT usd FROM wallet').fetchone()[0],9.5)
 async def test_invalid_confirmed_quote_does_not_start(self):
  async def render(cb):self.fail('provider must not be started')
  async def deliver(v):self.fail('delivery must not start')
  quote=service.TranslationQuote(5,.1,.01,5)
  with self.assertRaises(ValueError):
   await service.run_quoted(self.db,'bad-quote',1,quote,render=render,deliver=deliver)
