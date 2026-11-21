import asyncio, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from neyrobot_prod import jobs

class DummyClient:
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass

class KlingRecoveryAspectTest(unittest.IsolatedAsyncioTestCase):
    async def test_interrupted_job_preserves_selected_aspect(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate=asyncio.Event()
            async def interrupted(*args, **kwargs):
                gate.set()
                await asyncio.Future()
            mod=SimpleNamespace(DB_PATH=str(Path(tmp)/'subs.db'),_poll_video_task_generic=interrupted)
            jobs.patch_runtime(mod)
            update=SimpleNamespace(effective_user=SimpleNamespace(id=3),effective_chat=SimpleNamespace(id=7))
            task=asyncio.create_task(mod._poll_video_task_generic(update,None,{},'https://example.invalid',['/task/{id}'],'abc','Kling image→video',60,target_aspect='9:16'))
            await gate.wait();task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            job=jobs.pending_jobs(mod)[0]
            self.assertEqual(job['payload'].get('target_aspect'),'9:16')
            recovered=AsyncMock(return_value=True)
            mod._PROD_ORIGINAL_POLL_VIDEO=recovered
            mod.KLING_API_KEY='test';mod.COMET_BASE_URL='https://example.invalid'
            app=SimpleNamespace(bot=SimpleNamespace())
            with patch.object(jobs.httpx, "AsyncClient", return_value=DummyClient()):
                await jobs._recover_generic_video(mod,app,job)
            self.assertEqual(recovered.await_args.kwargs.get('target_aspect'),'9:16')
    async def test_legacy_job_without_aspect_still_recovers(self):
        recovered=AsyncMock(return_value=True)
        mod=SimpleNamespace(_PROD_ORIGINAL_POLL_VIDEO=recovered,KLING_API_KEY='test')
        job={'user_id':1,'chat_id':2,'provider':'kling','provider_task_id':'old','payload':{'base_url':'https://example.invalid','status_paths':['/task/{id}']}}
        with patch.object(jobs.httpx, "AsyncClient", return_value=DummyClient()):
            await jobs._recover_generic_video(mod,SimpleNamespace(bot=SimpleNamespace()),job)
        self.assertNotIn('target_aspect',recovered.await_args.kwargs)

class KlingDeliveryClaimTest(unittest.TestCase):
    def test_claim_survives_restart_and_blocks_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod=SimpleNamespace(DB_PATH=str(Path(tmp)/'db.sqlite'))
            jobs.begin_job(mod,user_id=3,chat_id=7,feature='video_generation',provider='kling',provider_task_id='task1')
            self.assertTrue(jobs.claim_kling_delivery(mod.DB_PATH,7,'task1'))
            self.assertFalse(jobs.claim_kling_delivery(mod.DB_PATH,7,'task1'))
            self.assertEqual(jobs.pending_jobs(mod),[])
    def test_other_chat_and_unknown_job_are_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod=SimpleNamespace(DB_PATH=str(Path(tmp)/'db.sqlite'))
            jobs.begin_job(mod,user_id=3,chat_id=7,feature='video_generation',provider='kling',provider_task_id='task1')
            self.assertTrue(jobs.claim_kling_delivery(mod.DB_PATH,8,'task1'))
            self.assertEqual(len(jobs.pending_jobs(mod)),1)

class KlingDeliveryIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_send_is_not_resent_after_restart(self):
        import ast, subprocess
        from io import BytesIO
        import logging
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'main.py';p.write_bytes((root/'main.py').read_bytes())
            for name in ('main_kling_billing_failures.patch','main_promo_attempts_v1.patch','main_kling_no_duplicate.patch','main_kling_aspect_delivery.patch','main_kling_delivery_claim.patch'):
                subprocess.run(['patch','--batch','-p1','-i',str(root/'ops'/name)],cwd=tmp,check=True,stdout=subprocess.DEVNULL)
            tree=ast.parse(p.read_text())
            wanted={'_claim_kling_video_delivery','_reply_video_bytes'}
            nodes=[n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name in wanted]
            db=str(Path(tmp)/'jobs.sqlite');mod=SimpleNamespace(DB_PATH=db)
            jobs.begin_job(mod,user_id=3,chat_id=7,feature='video_generation',provider='kling',provider_task_id='task1')
            fit=AsyncMock(side_effect=lambda content,caption,aspect:(content,caption))
            send=AsyncMock(side_effect=asyncio.CancelledError())
            update=SimpleNamespace(effective_chat=SimpleNamespace(id=7),effective_message=SimpleNamespace(reply_video=send))
            ns={'DB_PATH':db,'asyncio':asyncio,'BytesIO':BytesIO,'InputFile':lambda x:x,'VIDEO_RESULT_SEND_AS_DOCUMENT':False,'VIDEO_SEND_WRITE_TIMEOUT_S':10,'_fit_kling_delivery':fit,'_video_result_key':lambda *a,**k:'key','_mark_video_sent_once':lambda k:False,'log':logging.getLogger('test'),'Update':object}
            exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<patched-main>','exec'),ns)
            with self.assertRaises(asyncio.CancelledError):
                await ns['_reply_video_bytes'](update,b'x'*512,'done',task_id='task1',target_aspect='9:16')
            self.assertEqual(jobs.pending_jobs(mod),[])
            with self.assertRaises(RuntimeError):
                await ns['_reply_video_bytes'](update,b'x'*512,'done',task_id='task1',target_aspect='9:16')
            self.assertEqual(send.await_count,1)
