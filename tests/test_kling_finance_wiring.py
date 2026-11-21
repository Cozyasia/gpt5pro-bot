import ast,asyncio,json,logging,subprocess,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from neyrobot_prod.kling_finance_scope import OutcomeUnknown,run_scoped
ROOT=Path(__file__).resolve().parents[1]
class WiringTest(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'main.py';p.write_bytes((ROOT/'main.py').read_bytes())
   for name in ('main_kling_billing_failures.patch','main_promo_attempts_v1.patch','main_kling_no_duplicate.patch','main_kling_aspect_delivery.patch','main_kling_delivery_claim.patch'):
    subprocess.run(['patch','--batch','-p1','-i',str(ROOT/'ops'/name)],cwd=td,check=True,stdout=subprocess.DEVNULL)
   additional=ROOT/'ops/main_kling_finance_recovery.patch'
   if additional.exists(): subprocess.run(['patch','--batch','-p1','-i',str(additional)],cwd=td,check=True,stdout=subprocess.DEVNULL)
   self.source=p.read_text();tree=ast.parse(self.source)
  names={'_poll_video_task_generic','_credit_release_stale'}
  funcs=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
  self.ns={'__name__':'test','time':time,'json':json,'asyncio':asyncio,'log':logging.getLogger('test'),'Update':object,'httpx':SimpleNamespace(AsyncClient=object),'_api_error_preview':lambda r:'','_extract_first_url':lambda v:None,'CREDIT_RESERVATION_TTL_S':300}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*funcs],type_ignores=[])),'<test>','exec'),self.ns)
 async def test_pending_provider_timeout_does_not_release_or_repeat(self):
  response=SimpleNamespace(status_code=200,json=lambda:{'data':{'task_status':'processing'}})
  client=SimpleNamespace(get=AsyncMock(return_value=response))
  update=SimpleNamespace(effective_message=SimpleNamespace(reply_text=AsyncMock()))
  async def action():return await self.ns['_poll_video_task_generic'](update,client,{},'https://example.invalid',['/task/{id}'],'1','Kling image→video',max_wait_s=-1,target_aspect='9:16')
  with self.assertRaises(OutcomeUnknown):await run_scoped(action,'credit','tx',1,'image_to_video_kling')
 async def test_confirmed_failure_can_return_false(self):
  response=SimpleNamespace(status_code=200,json=lambda:{'data':{'task_status':'failed'}})
  client=SimpleNamespace(get=AsyncMock(return_value=response));update=SimpleNamespace(effective_message=SimpleNamespace(reply_text=AsyncMock()))
  async def action():return await self.ns['_poll_video_task_generic'](update,client,{},'https://example.invalid',['/task/{id}'],'1','Kling image→video',max_wait_s=-1,target_aspect='9:16')
  self.assertFalse(await run_scoped(action,'credit','tx',1,'image_to_video_kling'))
 async def test_unresolved_kling_reservation_does_not_expire(self):
  import sqlite3
  con=sqlite3.connect(':memory:');con.execute('CREATE TABLE credit_ledger(user_id INTEGER,feature TEXT,status TEXT,created_ts INTEGER,updated_ts INTEGER)')
  con.executemany('INSERT INTO credit_ledger VALUES(?,?,?,?,?)',[(1,'image_to_video_kling','reserved',1,1),(1,'other','reserved',1,1)])
  self.ns['_credit_release_stale'](con.cursor(),1)
  rows=dict(con.execute('SELECT feature,status FROM credit_ledger').fetchall())
  self.assertEqual(rows['image_to_video_kling'],'reserved');self.assertEqual(rows['other'],'released_timeout')
 async def test_paid_unknown_keeps_reserved_with_real_ledger(self):
  import sqlite3,uuid,contextlib,math
  from neyrobot_prod.kling_finance_scope import current
  tree=ast.parse(self.source)
  names={'_try_pay_then_do','_credit_reserve','_credit_release','_credit_commit','_credit_release_stale'}
  funcs=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
  with tempfile.TemporaryDirectory() as tmp:
   db=str(Path(tmp)/'db')
   with sqlite3.connect(db) as c:c.executescript('''CREATE TABLE wallet(user_id INTEGER PRIMARY KEY,usd REAL); INSERT INTO wallet VALUES(1,10); CREATE TABLE credit_ledger(tx_id TEXT PRIMARY KEY,user_id INTEGER,feature TEXT,engine TEXT,provider_cost_usd REAL,retail_usd REAL,credits REAL,status TEXT,metadata_json TEXT,created_ts INTEGER,updated_ts INTEGER);''')
   ns={'DB_PATH':db,'sqlite3':sqlite3,'uuid':uuid,'time':time,'json':json,'math':math,'contextlib':contextlib,'log':logging.getLogger('test'),'CREDIT_RESERVATION_TTL_S':300,'Update':object,'ContextTypes':SimpleNamespace(DEFAULT_TYPE=object),'_usd_to_credits':lambda v:v*100,'_retail_usd':lambda v:v,'_retail_credits':lambda v:v*100,'_try_consume_promo_daily5_quota':lambda *a:(False,0,5,'',None),'is_promo_daily5_user':lambda *a:False,'_free_quota_category':lambda *a:None,'is_unlimited':lambda *a:False,'NEYRONIX_PAID_CONFIRM_ENABLED':False}
   exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*funcs],type_ignores=[])),'<test>','exec'),ns)
   update=SimpleNamespace(effective_user=SimpleNamespace(username='x'),effective_message=SimpleNamespace(reply_text=AsyncMock()));ctx=SimpleNamespace(user_data={})
   async def provider():
    self.assertEqual(current()['kind'],'credit')
    raise OutcomeUnknown()
   await ns['_try_pay_then_do'](update,ctx,1,'kling',2,provider,remember_kind='image_to_video_kling')
   with sqlite3.connect(db) as c:
    self.assertEqual(c.execute('SELECT status FROM credit_ledger').fetchone()[0],'reserved')
    self.assertEqual(c.execute('SELECT usd FROM wallet').fetchone()[0],10)
   self.assertIn('Резерв сохранён',update.effective_message.reply_text.await_args.args[0])
 async def test_provider_id_saved_before_acceptance_message(self):
  from neyrobot_prod import jobs
  from unittest.mock import patch
  tree=ast.parse(self.source)
  func=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_create_and_poll_i2v')
  with tempfile.TemporaryDirectory() as tmp:
   db=str(Path(tmp)/'db.sqlite')
   response=SimpleNamespace(status_code=200,json=lambda:{'data':{'task_id':'accepted-id'}})
   client=SimpleNamespace(post=AsyncMock(return_value=response))
   class Client:
    async def __aenter__(self):return client
    async def __aexit__(self,*args):pass
   ns={'__name__':'test','DB_PATH':db,'httpx':SimpleNamespace(AsyncClient=lambda **kw:Client()),'Update':object,'ContextTypes':SimpleNamespace(DEFAULT_TYPE=object),'json':json,'log':logging.getLogger('test'),'LUMA_MAX_WAIT_S':20,'RUNWAY_MAX_WAIT_S':20,'_extract_first_url':lambda v:None}
   exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),func],type_ignores=[])),'<test>','exec'),ns)
   update=SimpleNamespace(effective_user=SimpleNamespace(id=1),effective_chat=SimpleNamespace(id=9),effective_message=SimpleNamespace(reply_text=AsyncMock(side_effect=asyncio.CancelledError())))
   async def action():return await ns['_create_and_poll_i2v'](update,'https://example.invalid','key',[('/create',{})],['/task/{id}'],'Kling image→video',target_aspect='9:16')
   with self.assertRaises(asyncio.CancelledError):await run_scoped(action,'credit','tx1',1,'image_to_video_kling')
   pending=jobs.pending_jobs(SimpleNamespace(DB_PATH=db))
   self.assertEqual(pending[0]['provider_task_id'],'accepted-id')
   self.assertEqual(pending[0]['payload']['finance']['reference'],'tx1')
 async def test_notification_failure_does_not_release_unknown_provider_result(self):
  tree=ast.parse(self.source);func=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_create_and_poll_i2v')
  response=SimpleNamespace(status_code=503)
  class Client:
   async def __aenter__(self):return SimpleNamespace(post=AsyncMock(return_value=response))
   async def __aexit__(self,*args):pass
  ns={'__name__':'test','httpx':SimpleNamespace(AsyncClient=lambda **kw:Client()),'Update':object,'ContextTypes':SimpleNamespace(DEFAULT_TYPE=object),'json':json,'log':logging.getLogger('test')}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),func],type_ignores=[])),'<test>','exec'),ns)
  update=SimpleNamespace(effective_message=SimpleNamespace(reply_text=AsyncMock(side_effect=ConnectionError('telegram unavailable'))))
  async def action():return await ns['_create_and_poll_i2v'](update,'https://example.invalid','key',[('/create',{})],[],'Kling image→video')
  with self.assertRaises(OutcomeUnknown):await run_scoped(action,'credit','tx',1,'image_to_video_kling')
