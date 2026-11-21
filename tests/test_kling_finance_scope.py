import asyncio,unittest
from types import SimpleNamespace
from neyrobot_prod import jobs
try:
 from neyrobot_prod.kling_finance_scope import run_scoped,current
except ImportError:
 run_scoped=current=None

class ScopeTest(unittest.IsolatedAsyncioTestCase):
 async def test_reservation_is_scoped_to_one_async_call(self):
  self.assertIsNotNone(run_scoped)
  async def op():
   await asyncio.sleep(0)
   return current()
  a,b=await asyncio.gather(run_scoped(op,'credit','a',1,'image_to_video_kling'),run_scoped(op,'promo','b',2,'image_to_video_kling'))
  self.assertEqual(a,{'kind':'credit','reference':'a','user_id':1})
  self.assertEqual(b,{'kind':'promo','reference':'b','user_id':2})
  self.assertIsNone(current())
 async def test_other_features_remain_unscoped(self):
  self.assertIsNotNone(run_scoped)
  async def op():return current()
  self.assertIsNone(await run_scoped(op,'credit','a',1,'image_to_video_runway'))

class JobScopeTest(unittest.IsolatedAsyncioTestCase):
 async def test_interrupted_provider_persists_reservation_identity(self):
  import tempfile,sqlite3
  from pathlib import Path
  with tempfile.TemporaryDirectory() as tmp:
   gate=asyncio.Event()
   async def waiting(*a,**kw):gate.set();await asyncio.Future()
   mod=SimpleNamespace(DB_PATH=str(Path(tmp)/'db'),_poll_video_task_generic=waiting)
   jobs.patch_runtime(mod)
   u=SimpleNamespace(effective_user=SimpleNamespace(id=1),effective_chat=SimpleNamespace(id=9))
   async def action():return await mod._poll_video_task_generic(u,None,{},'https://example.invalid',['/task/{id}'],'t1','Kling image→video',60,target_aspect='9:16')
   t=asyncio.create_task(run_scoped(action,'credit','tx1',1,'image_to_video_kling'))
   await gate.wait();t.cancel()
   with self.assertRaises(asyncio.CancelledError):await t
   pending=jobs.pending_jobs(mod)
   self.assertEqual(pending[0]['payload'].get('finance'),{'kind':'credit','reference':'tx1','user_id':1})
 async def test_recovered_poll_receives_original_finance_scope(self):
  from unittest.mock import patch
  seen=[]
  async def original(*a,**kw):seen.append(current());return True
  class Client:
   async def __aenter__(self):return self
   async def __aexit__(self,*args):pass
  mod=SimpleNamespace(_PROD_ORIGINAL_POLL_VIDEO=original,KLING_API_KEY='key')
  finance={'kind':'credit','reference':'tx1','user_id':1}
  job={'user_id':1,'chat_id':9,'provider':'kling','provider_task_id':'t1','payload':{'base_url':'https://example.invalid','status_paths':['/task/{id}'],'finance':finance,'target_aspect':'9:16'}}
  with patch.object(jobs.httpx,'AsyncClient',return_value=Client()):await jobs._recover_generic_video(mod,SimpleNamespace(bot=SimpleNamespace()),job)
  self.assertEqual(seen,[finance]);self.assertIsNone(current())

class RecoveryIntegrationTest(unittest.IsolatedAsyncioTestCase):
 async def test_recovery_delivers_once_and_charges_original_reservation(self):
  import tempfile,sqlite3
  from pathlib import Path
  from unittest.mock import patch,AsyncMock
  with tempfile.TemporaryDirectory() as tmp:
   path=str(Path(tmp)/'db.sqlite');mod=SimpleNamespace(DB_PATH=path,KLING_API_KEY='key')
   gate=asyncio.Event()
   async def interrupted(*a,**kw):gate.set();await asyncio.Future()
   mod._poll_video_task_generic=interrupted;jobs.patch_runtime(mod)
   with sqlite3.connect(path) as c:
    c.executescript("CREATE TABLE wallet(user_id INTEGER PRIMARY KEY,usd REAL); CREATE TABLE credit_ledger(tx_id TEXT PRIMARY KEY,user_id INTEGER,retail_usd REAL,status TEXT,updated_ts INTEGER); INSERT INTO wallet VALUES(1,10); INSERT INTO credit_ledger VALUES('tx1',1,2,'reserved',0);")
   update=SimpleNamespace(effective_user=SimpleNamespace(id=1),effective_chat=SimpleNamespace(id=9))
   async def action():return await mod._poll_video_task_generic(update,None,{},'https://example.invalid',['/task/{id}'],'t1','Kling image→video',60,target_aspect='9:16')
   t=asyncio.create_task(run_scoped(action,'credit','tx1',1,'image_to_video_kling'));await gate.wait();t.cancel()
   with self.assertRaises(asyncio.CancelledError):await t
   sends=[]
   async def restored(update,*a,**kw):
    self.assertEqual(current()['reference'],'tx1')
    if jobs.claim_kling_delivery(path,9,'t1'):sends.append('sent')
    return True
   class Client:
    async def __aenter__(self):return self
    async def __aexit__(self,*a):pass
   mod._PROD_ORIGINAL_POLL_VIDEO=restored;app=SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
   with patch.object(jobs.httpx,'AsyncClient',return_value=Client()), patch.object(jobs,'_PROCESS_INSTANCE','restarted-process'):
    await jobs.recover_pending(mod,app);await jobs.recover_pending(mod,app)
   self.assertEqual(sends,['sent'])
   with sqlite3.connect(path) as c:
    self.assertEqual(c.execute('SELECT usd FROM wallet').fetchone()[0],8)
    self.assertEqual(c.execute('SELECT status FROM credit_ledger').fetchone()[0],'charged')
    self.assertEqual(c.execute('SELECT state FROM durable_jobs').fetchone()[0],'completed')
 async def test_recovery_does_not_poll_jobs_still_running_in_same_process(self):
  import tempfile
  from pathlib import Path
  from unittest.mock import AsyncMock
  with tempfile.TemporaryDirectory() as td:
   path=str(Path(td)/'db');mod=SimpleNamespace(DB_PATH=path,_PROD_ORIGINAL_POLL_VIDEO=AsyncMock(return_value=True))
   jobs.begin_job(mod,user_id=1,chat_id=9,feature='video_generation',provider='kling',provider_task_id='active',payload={})
   await jobs.recover_pending(mod,SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock())))
   mod._PROD_ORIGINAL_POLL_VIDEO.assert_not_awaited()
   self.assertEqual(len(jobs.pending_jobs(mod)),1)
 async def test_timeout_releases_process_ownership_for_background_recovery(self):
  import tempfile
  from pathlib import Path
  from neyrobot_prod.kling_finance_scope import OutcomeUnknown
  with tempfile.TemporaryDirectory() as td:
   async def waiting(*a,**kw):raise OutcomeUnknown()
   mod=SimpleNamespace(DB_PATH=str(Path(td)/'db'),_poll_video_task_generic=waiting);jobs.patch_runtime(mod)
   u=SimpleNamespace(effective_user=SimpleNamespace(id=1),effective_chat=SimpleNamespace(id=9))
   async def action():return await mod._poll_video_task_generic(u,None,{},'https://example.invalid',['/task/{id}'],'x','Kling image→video',60,target_aspect='9:16')
   with self.assertRaises(OutcomeUnknown):await run_scoped(action,'credit','tx',1,'image_to_video_kling')
   self.assertNotEqual(jobs.pending_jobs(mod)[0]['payload'].get('_process_instance'),jobs._PROCESS_INSTANCE)
 async def test_recovery_confirmed_failure_returns_promo_once(self):
  import tempfile,sqlite3
  from pathlib import Path
  from unittest.mock import patch,AsyncMock
  with tempfile.TemporaryDirectory() as td:
   path=str(Path(td)/'db');mod=SimpleNamespace(DB_PATH=path,KLING_API_KEY='key')
   finance={'kind':'promo','reference':'promo1','user_id':1}
   jobs.begin_job(mod,user_id=1,chat_id=9,feature='video_generation',provider='kling',provider_task_id='t1',payload={'base_url':'https://example.invalid','status_paths':['/task/{id}'],'finance':finance,'target_aspect':'9:16'})
   with sqlite3.connect(path) as c:c.executescript("CREATE TABLE kv(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE promo_attempts(token TEXT PRIMARY KEY,quota_key TEXT,status TEXT); INSERT INTO kv VALUES('promo5:1:20261121:kling','1'); INSERT INTO promo_attempts VALUES('promo1','promo5:1:20261121:kling','reserved');")
   mod._PROD_ORIGINAL_POLL_VIDEO=AsyncMock(return_value=False)
   class Client:
    async def __aenter__(self):return self
    async def __aexit__(self,*a):pass
   app=SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
   with patch.object(jobs.httpx,'AsyncClient',return_value=Client()),patch.object(jobs,'_PROCESS_INSTANCE','restart'):
    await jobs.recover_pending(mod,app);await jobs.recover_pending(mod,app)
   with sqlite3.connect(path) as c:
    self.assertEqual(c.execute('SELECT value FROM kv').fetchone()[0],'0')
    self.assertEqual(c.execute('SELECT status FROM promo_attempts').fetchone()[0],'released')
 async def test_active_jobs_cannot_starve_recovery_queue(self):
  import tempfile
  from pathlib import Path
  from unittest.mock import patch,AsyncMock
  with tempfile.TemporaryDirectory() as td:
   mod=SimpleNamespace(DB_PATH=str(Path(td)/'db'),_PROD_ORIGINAL_POLL_VIDEO=AsyncMock(return_value=True),KLING_API_KEY='key')
   for i in range(105):jobs.begin_job(mod,user_id=1,chat_id=9,feature='video_generation',provider='kling',provider_task_id=f'active{i}')
   with patch.object(jobs,'_PROCESS_INSTANCE','previous'):
    jobs.begin_job(mod,user_id=1,chat_id=9,feature='video_generation',provider='kling',provider_task_id='old',payload={'base_url':'https://example.invalid','status_paths':['/task/{id}']})
   class Client:
    async def __aenter__(self):return self
    async def __aexit__(self,*a):pass
   with patch.object(jobs.httpx,'AsyncClient',return_value=Client()):await jobs.recover_pending(mod,SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock())))
   self.assertEqual(mod._PROD_ORIGINAL_POLL_VIDEO.await_count,1)
