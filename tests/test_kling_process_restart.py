import asyncio,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from neyrobot_prod import jobs

CHILD=r'''import asyncio, os, sys
from types import SimpleNamespace
from neyrobot_prod import jobs
from neyrobot_prod.kling_finance_scope import run_scoped
path,mode=sys.argv[1:]
async def poll(*args,**kwargs):
 if mode=='during_send':jobs.claim_kling_delivery(path,9,'task-1')
 os._exit(73)
mod=SimpleNamespace(DB_PATH=path,_poll_video_task_generic=poll)
jobs.patch_runtime(mod)
u=SimpleNamespace(effective_user=SimpleNamespace(id=1),effective_chat=SimpleNamespace(id=9))
async def action():return await mod._poll_video_task_generic(u,None,{},'https://example.invalid',['/task/{id}'],'task-1','Kling image→video',60,target_aspect='9:16')
asyncio.run(run_scoped(action,'credit','tx-1',1,'image_to_video_kling'))'''

class ProcessRestartTest(unittest.IsolatedAsyncioTestCase):
 async def run_scenario(self,mode):
  with tempfile.TemporaryDirectory() as td:
   path=str(Path(td)/'db.sqlite')
   with sqlite3.connect(path) as c:c.executescript("CREATE TABLE wallet(user_id INTEGER PRIMARY KEY,usd REAL); INSERT INTO wallet VALUES(1,10); CREATE TABLE credit_ledger(tx_id TEXT PRIMARY KEY,user_id INTEGER,retail_usd REAL,status TEXT,updated_ts INTEGER); INSERT INTO credit_ledger VALUES('tx-1',1,2,'reserved',0);")
   proc=subprocess.run([sys.executable,'-c',CHILD,path,mode],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
   self.assertEqual(proc.returncode,73)
   sent=[]
   async def poll(update,*args,**kwargs):
    if jobs.claim_kling_delivery(path,9,'task-1'):sent.append(1)
    return True
   class Client:
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
   mod=SimpleNamespace(DB_PATH=path,KLING_API_KEY='test',_PROD_ORIGINAL_POLL_VIDEO=poll)
   with patch.object(jobs.httpx,'AsyncClient',return_value=Client()):await jobs.recover_pending(mod,SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock())))
   with sqlite3.connect(path) as c:
    return sent,c.execute('SELECT usd FROM wallet').fetchone()[0],c.execute('SELECT status FROM credit_ledger').fetchone()[0],c.execute('SELECT state FROM durable_jobs').fetchone()[0]
 async def test_process_death_during_poll_restores_and_charges_once(self):
  self.assertEqual(await self.run_scenario('poll'),([1],8,'charged','completed'))
 async def test_process_death_during_send_does_not_resend_or_charge(self):
  self.assertEqual(await self.run_scenario('during_send'),([],10,'reserved','delivery_uncertain'))
