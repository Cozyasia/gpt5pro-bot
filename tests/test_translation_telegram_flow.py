import os
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from neyrobot_prod import translation_telegram_flow as flow

class AccessTests(unittest.TestCase):
 def test_restricted_test_access_and_global_switch(self):
  with patch.dict(os.environ, {}, clear=True):
   self.assertFalse(flow.enabled_for_user(12))
  with patch.dict(os.environ, {'TRANSLATION_QUOTED_TEST_USER_IDS':'12, 17'}, clear=True):
   self.assertTrue(flow.enabled_for_user(12))
   self.assertFalse(flow.enabled_for_user(13))
  with patch.dict(os.environ, {'TRANSLATION_QUOTED_FLOW_ENABLED':'true'}, clear=True):
   self.assertTrue(flow.enabled_for_user(13))

 def test_rendered_integration_checks_access_at_entry_and_callback(self):
  from test_seedance_aspect_selection import patched_source
  source=patched_source(include_owner=True)
  self.assertIn('enabled_for_user(q.from_user.id)', source)
  self.assertIn('enabled_for_user(update.effective_user.id)', source)

class Message:
 def __init__(self): self.message_id=47; self.sent=[]
 async def reply_text(self,text,**kw): self.sent.append((text,kw))

class Query:
 def __init__(self, msg, data, user): self.message=msg; self.data=data; self.from_user=user; self.answers=[]
 async def answer(self,*args,**kw): self.answers.append((args,kw))

class FlowTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.user=SimpleNamespace(id=12,username='user'); self.msg=Message()
  self.update=SimpleNamespace(effective_user=self.user,effective_chat=SimpleNamespace(id=20),effective_message=self.msg)
  self.ctx=SimpleNamespace(user_data={'video_translation_language':'en'},application=SimpleNamespace(bot_data={}))
  self.enabled=True
  self.g={'InlineKeyboardButton':lambda text,callback_data: (text,callback_data),
    'InlineKeyboardMarkup':lambda rows:rows,'_generated_video_duration_seconds_sync':lambda v:5.0,
    'OPENAI_STT_KEY':'x','OPENAI_TTS_KEY':'x','TEXT_API_KEY':'x','KLING_LIPSYNC_ENABLED':True,'KLING_API_KEY':'',
    'COMET_API_KEY':'x','_retail_usd':lambda cost:.5,'_retail_credits':lambda cost:50,
    'is_unlimited':lambda uid,name:self.enabled,'is_promo_daily5_user':lambda uid,name:False,
    '_wallet_available_get':lambda uid:10,'DB_PATH':'unused',
    '_provider_input_url_from_bytes':lambda *args:'https://example.org'}
  self.rates={v:'0.01' for v in flow.PRICE_KEYS.values()}
 async def test_quote_unlimited_then_duplicate_confirmation_runs_once(self):
  calls=[]
  async def run(**kw):calls.append(kw); return SimpleNamespace(state='delivered')
  with patch.dict(os.environ,self.rates),patch.object(flow,'run_short_translation',run):
   await flow.prepare(self.update,self.ctx,b'video',self.g)
   self.assertIn('0 кр.',self.msg.sent[-1][0])
   token=next(iter(self.ctx.application.bot_data['_translation_quotes']))
   q=Query(self.msg,'vtr:yes:'+token,self.user); self.update.callback_query=q
   await flow.callback(self.update,self.ctx,self.g); await flow.callback(self.update,self.ctx,self.g)
  self.assertEqual(len(calls),1); self.assertFalse(calls[0]['charge_user'])
  self.assertEqual(calls[0]['request_id'],'translation:20:47')
 async def test_missing_prices_never_produces_quote(self):
  with patch.dict(os.environ,{v:'' for v in flow.PRICE_KEYS.values()}):
   await flow.prepare(self.update,self.ctx,b'video',self.g)
  self.assertIn('Стоимость пока недоступна',self.msg.sent[-1][0])
  self.assertFalse(self.ctx.application.bot_data.get('_translation_quotes'))
 async def test_changed_entitlement_blocks_start(self):
  with patch.dict(os.environ,self.rates):await flow.prepare(self.update,self.ctx,b'video',self.g)
  token=next(iter(self.ctx.application.bot_data['_translation_quotes']));self.enabled=False
  q=Query(self.msg,'vtr:yes:'+token,self.user);self.update.callback_query=q
  with patch.object(flow,'run_short_translation') as run: await flow.callback(self.update,self.ctx,self.g)
  run.assert_not_called();self.assertIn('изменились',q.answers[-1][0][0])
 async def test_busy_service_keeps_quote_without_starting(self):
  with patch.dict(os.environ,self.rates):await flow.prepare(self.update,self.ctx,b'video',self.g)
  token=next(iter(self.ctx.application.bot_data['_translation_quotes']))
  self.ctx.application.bot_data['_translation_running']={'one','two'}
  q=Query(self.msg,'vtr:yes:'+token,self.user);self.update.callback_query=q
  with patch.object(flow,'run_short_translation') as run:await flow.callback(self.update,self.ctx,self.g)
  run.assert_not_called();self.assertIn(token,self.ctx.application.bot_data['_translation_quotes'])
  self.assertIn('занят',q.answers[-1][0][0])
 async def test_promo_account_is_not_accidentally_charged(self):
  self.enabled=False;self.g['is_promo_daily5_user']=lambda *args:True
  with patch.dict(os.environ,self.rates):await flow.prepare(self.update,self.ctx,b'video',self.g)
  self.assertIn('промо-тарифа',self.msg.sent[-1][0])
  self.assertFalse(self.ctx.application.bot_data.get('_translation_quotes'))
 async def test_test_only_mode_rejects_non_unlimited_accounts(self):
  self.enabled=False
  with patch.dict(os.environ,{**self.rates,'TRANSLATION_QUOTED_TEST_USER_IDS':'12'},clear=True):
   await flow.prepare(self.update,self.ctx,b'video',self.g)
  self.assertIn('тест',self.msg.sent[-1][0].lower())
  self.assertFalse(self.ctx.application.bot_data.get('_translation_quotes'))
 async def test_file_test_mode_rejects_non_unlimited_accounts(self):
  self.enabled=False
  with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'DB_PATH':root+'/db.sqlite'}, clear=True):
   Path(root,'translation_quoted_test.json').write_text(json.dumps({'user_id':12,'prices':{key:0.01 for key in flow.PRICE_KEYS}}))
   await flow.prepare(self.update,self.ctx,b'video',self.g)
  self.assertIn('тест',self.msg.sent[-1][0].lower())
  self.assertFalse(self.ctx.application.bot_data.get('_translation_quotes'))
 async def test_other_account_cannot_confirm_quote(self):
  with patch.dict(os.environ,self.rates):await flow.prepare(self.update,self.ctx,b'video',self.g)
  token=next(iter(self.ctx.application.bot_data['_translation_quotes']))
  q=Query(self.msg,'vtr:yes:'+token,SimpleNamespace(id=13,username='other'));self.update.callback_query=q
  with patch.object(flow,'run_short_translation') as run: await flow.callback(self.update,self.ctx,self.g)
  run.assert_not_called();self.assertIn(token,self.ctx.application.bot_data['_translation_quotes'])
 async def test_translation_failure_text_is_not_sent_to_tts_or_kling(self):
  async def stt(*args,**kwargs): return 'speech'
  async def translate(*args,**kwargs): return '⚠️ Сейчас не получилось получить ответ от модели. Попробуйте позже.'
  def tts(*args):self.fail('must not synthesize an error message')
  self.g.update(_extract_video_audio_sync=lambda video:b'audio',_stt_transcribe_bytes=stt,
                ask_openai_text=translate,_tts_bytes_sync=tts)
  calls=[]
  async def run(**kw):
   with self.assertRaises(RuntimeError):await kw['transcribe_and_dub'](b'video',5,'English')
   calls.append(1);return SimpleNamespace(state='unknown')
  with patch.dict(os.environ,self.rates),patch.object(flow,'run_short_translation',run):
   await flow.prepare(self.update,self.ctx,b'video',self.g)
   token=next(iter(self.ctx.application.bot_data['_translation_quotes']))
   self.update.callback_query=Query(self.msg,'vtr:yes:'+token,self.user)
   await flow.callback(self.update,self.ctx,self.g)
  self.assertEqual(calls,[1])
 async def test_real_ledger_flow_delivers_then_charges_once(self):
  from neyrobot_prod import translation_public_flow
  with tempfile.TemporaryDirectory() as td:
   db=str(Path(td)/'wallet.db')
   with sqlite3.connect(db) as c:c.executescript('''CREATE TABLE wallet(user_id INTEGER PRIMARY KEY,usd REAL);
   INSERT INTO wallet VALUES(12,1); CREATE TABLE credit_ledger(tx_id TEXT PRIMARY KEY,user_id INTEGER,
   feature TEXT,engine TEXT,provider_cost_usd REAL,retail_usd REAL,credits REAL,status TEXT,
   metadata_json TEXT,created_ts INTEGER,updated_ts INTEGER);''')
   self.enabled=False; events=[]
   async def stt(*args,**kwargs):return 'hello'
   async def translate(*args,**kwargs):return 'hola'
   async def kling(video,audio,**kw):events.append('kling');kw['on_provider_state']('lip_sync_task_id','job-1');return b'result'
   async def reply(update,video,caption,**kw):
    with sqlite3.connect(db) as c:self.assertEqual(c.execute('SELECT usd FROM wallet').fetchone()[0],1)
    events.append('delivery');return True
   async def sync(video,duration,segment):return await segment(b'clip',b'audio',5000)
   self.g.update(DB_PATH=db,_extract_video_audio_sync=lambda v:b'audio',_stt_transcribe_bytes=stt,
    ask_openai_text=translate,_split_tts_text=lambda t,n:[t],TTS_MAX_CHARS=100,
    _tts_bytes_sync=lambda *a,**kw:b'speech',_avatar_tts_voice_get=lambda c:'voice',
    _concat_audio_mp3_sync=lambda parts:b'audio',_mux_translated_audio_sync=lambda *a:b'video',
    _run_kling_lipsync_result_bytes=kling,_reply_video_bytes=reply)
   with patch.dict(os.environ,self.rates),patch.object(translation_public_flow,'sync_translated_video',sync):
    await flow.prepare(self.update,self.ctx,b'video',self.g)
    token=next(iter(self.ctx.application.bot_data['_translation_quotes']))
    self.update.callback_query=Query(self.msg,'vtr:yes:'+token,self.user)
    await flow.callback(self.update,self.ctx,self.g);await flow.callback(self.update,self.ctx,self.g)
   with sqlite3.connect(db) as c:
    self.assertEqual(c.execute('SELECT usd FROM wallet').fetchone()[0],.5)
    self.assertEqual(c.execute('SELECT status FROM credit_ledger').fetchone()[0],'charged')
   self.assertEqual(events,['kling','delivery'])

class DeploymentIntegrationTests(unittest.TestCase):
 def test_container_patches_connect_translation_to_telegram(self):
  from test_seedance_aspect_selection import patched_source
  source=patched_source(include_owner=True)
  self.assertIn('await open_menu(update, context, globals())',source)
  self.assertIn('await prepare(update, context, raw, globals())',source)
  self.assertIn('CallbackQueryHandler(_translation_callback',source)
  self.assertIn('retry_unknown_post=retry_identify_unknown',source)
  self.assertIn("status='reserved'\", (int(user_id),))",source)

class NoRetryTests(unittest.IsolatedAsyncioTestCase):
 async def test_translation_stt_makes_only_one_provider_attempt(self):
  import ast,asyncio
  from test_seedance_aspect_selection import patched_source
  tree=ast.parse(patched_source(include_owner=True))
  nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in ('_oai_stt_client','_stt_transcribe_bytes')]
  from io import BytesIO
  calls=[]
  class Client:
   def __init__(self,**kw): calls.append(('client',kw['max_retries'])); self.audio=SimpleNamespace(transcriptions=self)
   def create(self,**kw): calls.append(('request',None)); raise TimeoutError('uncertain')
  async def sleep(*args): pass
  env={'_OpenAI_STT':Client,'OPENAI_STT_KEY':'x','OPENAI_STT_BASE_URL':'https://example.test',
       'OPENAI_STT_MODEL':'model','BytesIO':BytesIO,'asyncio':SimpleNamespace(sleep=sleep),
       'log':SimpleNamespace(warning=lambda *a:None,error=lambda *a:None)}
  exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<stt>','exec'),env)
  self.assertEqual(await env['_stt_transcribe_bytes']('file.mp3',b'audio',max_attempts=1),'')
  self.assertEqual(calls,[('client',0),('request',None)])
 async def test_translation_tts_makes_only_one_provider_attempt(self):
  import ast
  from test_seedance_aspect_selection import patched_source
  tree=ast.parse(patched_source(include_owner=True))
  fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_tts_bytes_sync')
  calls=[]
  class Timeout(Exception):pass
  class Client:
   def __init__(self,**kw):pass
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def post(self,*a,**kw):calls.append('post');raise Timeout()
  http=SimpleNamespace(Client=Client,Timeout=lambda **kw:None,ReadTimeout=Timeout,ConnectTimeout=Timeout,ConnectError=Timeout)
  env={'httpx':http,'OPENAI_TTS_KEY':'test','OPENAI_TTS_BASE_URL':'https://example.test',
       'OPENAI_TTS_MODEL':'test','OPENAI_TTS_VOICE':'alloy',
       'log':SimpleNamespace(warning=lambda *a:None,exception=lambda *a:None,info=lambda *a:None)}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<tts>','exec'),env)
  self.assertIsNone(env['_tts_bytes_sync']('text','mp3',max_attempts=1))
  self.assertEqual(calls,['post'])

