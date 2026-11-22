import asyncio, unittest
from types import SimpleNamespace
from neyrobot_prod.kling_background import schedule_i2v, schedule_confirmation

class Msg:
    def __init__(self): self.messages=[]
    async def reply_text(self,text,**kw): self.messages.append(text)
class App:
    def __init__(self): self.bot_data={}; self.tasks=[]
    def create_task(self,coro, **kw):
        task=asyncio.create_task(coro); self.tasks.append(task); return task
class BackgroundTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_updates_and_duplicate_are_safe(self):
        self.assertIsNotNone(schedule_i2v, 'background scheduling is not implemented')
        app=App(); msg=Msg(); user=SimpleNamespace(id=12)
        update=SimpleNamespace(effective_user=user,effective_message=msg)
        context=SimpleNamespace(application=app,user_data={'i2v_engine':'kling','i2v_duration':5})
        proceed=asyncio.Event(); started=asyncio.Event(); observed=[]
        async def generate(u,c,p,reference_bytes=None):
            started.set(); await proceed.wait(); observed.append((c.user_data['i2v_duration'],reference_bytes))
        await schedule_i2v(update,context,'walk',generate,lambda uid:b'photo')
        await asyncio.wait_for(started.wait(),1)
        context.user_data['i2v_duration']=30
        await schedule_i2v(update,context,'again',generate,lambda uid:b'other')
        self.assertEqual(len(app.tasks),1)
        self.assertTrue(any('уже' in s for s in msg.messages))
        proceed.set(); await asyncio.gather(*app.tasks)
        self.assertEqual(observed,[(5,b'photo')])
        self.assertFalse(app.bot_data['_kling_background_running'])
    async def test_confirmation_is_guarded_before_scheduling(self):
        self.assertIsNotNone(schedule_confirmation, 'background confirmation is not implemented')
        app=App(); msg=Msg(); u=SimpleNamespace(id=12); q=SimpleNamespace(from_user=u,message=msg)
        update=SimpleNamespace(effective_user=u,effective_message=msg,callback_query=q)
        ctx=SimpleNamespace(application=app,user_data={})
        e=asyncio.Event(); calls=[]
        async def confirm(update,context): calls.append(1); await e.wait()
        await schedule_confirmation(update,ctx,confirm)
        await schedule_confirmation(update,ctx,confirm)
        self.assertEqual(len(app.tasks),1)
        e.set(); await asyncio.gather(*app.tasks)
        self.assertEqual(calls,[1])

    async def test_failure_releases_lock_and_can_retry(self):
        app=App(); msg=Msg(); update=SimpleNamespace(effective_user=SimpleNamespace(id=12),effective_message=msg)
        ctx=SimpleNamespace(application=app,user_data={'i2v_engine':'kling'})
        async def bad(*args,**kwargs): raise RuntimeError('simulated')
        await schedule_i2v(update,ctx,'walk',bad,lambda uid:b'photo')
        await asyncio.gather(*app.tasks)
        self.assertFalse(app.bot_data['_kling_background_running'])
        self.assertTrue(any('статус' in s for s in msg.messages))
        async def good(*args,**kwargs): return True
        await schedule_i2v(update,ctx,'retry',good,lambda uid:b'photo')
        await app.tasks[-1]
        self.assertEqual(len(app.tasks),2)

    async def test_other_user_can_start_while_one_user_waits(self):
        app=App(); msg=Msg(); done=asyncio.Event(); started=[]
        ctx=SimpleNamespace(application=app,user_data={'i2v_engine':'kling'})
        async def generate(update,*args,**kwargs): started.append(update.effective_user.id); await done.wait()
        for uid in (12,13):
            update=SimpleNamespace(effective_user=SimpleNamespace(id=uid),effective_message=msg)
            await schedule_i2v(update,ctx,'walk',generate,lambda _:b'photo')
        await asyncio.sleep(0)
        self.assertEqual(started,[12,13])
        done.set(); await asyncio.gather(*app.tasks)
