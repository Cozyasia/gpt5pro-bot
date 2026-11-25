import sqlite3,tempfile,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
try:
 from neyrobot_prod import translation_credit_ledger as ledger
except ImportError:
 ledger=None

class TranslationCreditLedgerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.db=str(Path(self.tmp.name)/'wallet.db')
  with sqlite3.connect(self.db) as c:
   c.executescript('''CREATE TABLE wallet (user_id INTEGER PRIMARY KEY, usd REAL DEFAULT 0); CREATE TABLE credit_ledger (tx_id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,feature TEXT NOT NULL,engine TEXT NOT NULL,provider_cost_usd REAL NOT NULL,retail_usd REAL NOT NULL,credits REAL NOT NULL,status TEXT NOT NULL,metadata_json TEXT,created_ts INTEGER NOT NULL,updated_ts INTEGER NOT NULL); INSERT INTO wallet VALUES (1,10);''')
 def tearDown(self): self.tmp.cleanup()
 def reserve(self, key='update-1', user=1, retail=2):
  self.assertIsNotNone(ledger,'translation credit ledger is not implemented')
  return ledger.reserve(self.db,key,user,provider_cost=1,retail_cost=retail,credits=20)
 def state(self):
  with sqlite3.connect(self.db) as c:
   return (c.execute('SELECT usd FROM wallet WHERE user_id=1').fetchone()[0], c.execute('SELECT status FROM credit_ledger').fetchone()[0])
 def test_success_charges_once_even_under_duplicate_completion(self):
  tx=self.reserve();ledger.begin_provider(self.db,'update-1',1);ledger.record_provider_task(self.db,'update-1',1,'task-1')
  with ThreadPoolExecutor(max_workers=2) as ex:
   list(ex.map(lambda _:ledger.settle(self.db,'update-1',1,'delivered'),range(2)))
  self.assertEqual(self.state(),(8,'charged'))
 def test_unknown_outcome_preserves_reservation(self):
  self.reserve();ledger.begin_provider(self.db,'update-1',1);ledger.settle(self.db,'update-1',1,'unknown')
  self.assertEqual(self.state(),(10,'reserved'))
 def test_unknown_delivery_can_be_reconciled_without_second_charge(self):
  self.reserve();ledger.begin_provider(self.db,'update-1',1);ledger.record_provider_task(self.db,'update-1',1,'task-1')
  ledger.settle(self.db,'update-1',1,'unknown')
  self.assertTrue(ledger.settle(self.db,'update-1',1,'delivered'))
  self.assertFalse(ledger.settle(self.db,'update-1',1,'delivered'))
  self.assertEqual(self.state(),(8,'charged'))
 def test_confirmed_failure_releases_reservation(self):
  self.reserve();ledger.begin_provider(self.db,'update-1',1);ledger.settle(self.db,'update-1',1,'failed')
  self.assertEqual(self.state(),(10,'released'))
 def test_duplicate_request_cannot_launch_twice(self):
  tx=self.reserve();self.assertEqual(self.reserve(),tx)
  self.assertTrue(ledger.begin_provider(self.db,'update-1',1))
  self.assertFalse(ledger.begin_provider(self.db,'update-1',1))
 def test_existing_request_cannot_be_reused_by_different_user_or_quote(self):
  self.reserve()
  with self.assertRaises(ValueError):self.reserve(user=2)
  with self.assertRaises(ValueError):self.reserve(retail=3)
 def test_rejects_insufficient_balance_or_invalid_quote(self):
  with self.assertRaises(ValueError):self.reserve(retail=11)
  with self.assertRaises(ValueError):self.reserve(key='x',retail=float('nan'))
 def test_conflicting_terminal_status_is_rejected(self):
  self.reserve();ledger.begin_provider(self.db,'update-1',1);ledger.settle(self.db,'update-1',1,'failed')
  with self.assertRaises(ValueError):ledger.settle(self.db,'update-1',1,'delivered')
 def test_same_provider_task_cannot_be_charged_for_two_requests(self):
  self.reserve();self.reserve(key='update-2')
  ledger.begin_provider(self.db,'update-1',1);ledger.begin_provider(self.db,'update-2',1)
  ledger.record_provider_task(self.db,'update-1',1,'same-task')
  with self.assertRaises(ValueError):ledger.record_provider_task(self.db,'update-2',1,'same-task')
 def test_concurrent_duplicate_reservations_share_one_hold(self):
  with ThreadPoolExecutor(max_workers=2) as ex:
   ids=list(ex.map(lambda _:self.reserve(),range(2)))
  self.assertEqual(ids[0],ids[1])
  with sqlite3.connect(self.db) as c:
   self.assertEqual(c.execute('SELECT count(*) FROM credit_ledger').fetchone()[0],1)
 def test_other_reservations_reduce_available_balance(self):
  self.reserve(retail=8)
  with self.assertRaises(ValueError):self.reserve(key='update-2',retail=3)

class TranslationReservationExpiryTests(unittest.TestCase):
 def test_stale_cleanup_does_not_release_unresolved_translation(self):
  import ast,time
  from test_seedance_aspect_selection import patched_source
  tree=ast.parse(patched_source(include_owner=True))
  fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_credit_release_stale')
  env={'time':time,'CREDIT_RESERVATION_TTL_S':300}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<expiry>','exec'),env)
  with sqlite3.connect(':memory:') as c:
   c.execute('CREATE TABLE credit_ledger(user_id INTEGER, feature TEXT, status TEXT, created_ts INTEGER, updated_ts INTEGER)')
   c.execute("INSERT INTO credit_ledger VALUES(1,'video_translation_lipsync','reserved',1,1)")
   env['_credit_release_stale'](c.cursor(),1)
   self.assertEqual(c.execute('SELECT status FROM credit_ledger').fetchone()[0],'reserved')

class TranslationPaidExecutorTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=str(Path(self.tmp.name)/'db.sqlite')
  with sqlite3.connect(self.db) as c:
   c.executescript('''CREATE TABLE wallet(user_id INTEGER PRIMARY KEY,usd REAL); INSERT INTO wallet VALUES(1,10); CREATE TABLE credit_ledger(tx_id TEXT PRIMARY KEY,user_id INTEGER,feature TEXT,engine TEXT,provider_cost_usd REAL,retail_usd REAL,credits REAL,status TEXT,metadata_json TEXT,created_ts INTEGER,updated_ts INTEGER);''')
 async def asyncTearDown(self):self.tmp.cleanup()
 async def test_execute_delivers_then_charges_once(self):
  events=[]
  async def render(on_task):events.append('render');on_task('task-1');return b'video'
  async def send(video):events.append('send');self.assertEqual(video,b'video');return True
  kwargs=dict(provider_cost=1,retail_cost=2,credits=20,render=render,deliver=send)
  result=await ledger.execute(self.db,'request',1,**kwargs)
  second=await ledger.execute(self.db,'request',1,**kwargs)
  self.assertEqual(result,'delivered');self.assertEqual(second,'already_started');self.assertEqual(events,['render','send'])
  with sqlite3.connect(self.db) as c:self.assertEqual(c.execute('SELECT usd FROM wallet').fetchone()[0],8)
 async def test_uncertain_provider_or_delivery_keeps_hold(self):
  async def render(on_task):on_task('task-1');return b'video'
  async def send(video):raise TimeoutError('delivery ambiguous')
  state=await ledger.execute(self.db,'request',1,provider_cost=1,retail_cost=2,credits=20,render=render,deliver=send)
  self.assertEqual(state,'unknown')
  with sqlite3.connect(self.db) as c:self.assertEqual(c.execute('SELECT status FROM credit_ledger').fetchone()[0],'reserved')
 async def test_unconfirmed_delivery_does_not_charge(self):
  async def render(on_task):on_task('task-1');return b'video'
  async def send(video):return None
  state=await ledger.execute(self.db,'request',1,provider_cost=1,retail_cost=2,credits=20,render=render,deliver=send)
  self.assertEqual(state,'unknown')
  with sqlite3.connect(self.db) as c:self.assertEqual(c.execute('SELECT status FROM credit_ledger').fetchone()[0],'reserved')
 async def test_definitive_failure_releases_hold(self):
  async def render(on_task):raise ledger.ConfirmedFailure('provider refused')
  async def send(video):self.fail('must not send')
  state=await ledger.execute(self.db,'request',1,provider_cost=1,retail_cost=2,credits=20,render=render,deliver=send)
  self.assertEqual(state,'failed')
  with sqlite3.connect(self.db) as c:self.assertEqual(c.execute('SELECT status FROM credit_ledger').fetchone()[0],'released')
