import ast
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from test_seedance_aspect_selection import patched_source

class TranslationOwnerPipelineTests(unittest.IsolatedAsyncioTestCase):
 async def test_test_access_can_be_scoped_to_a_persistent_file(self):
  import os
  from unittest.mock import patch
  tree=ast.parse(patched_source(include_owner=True))
  fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_can_run_translation_test')
  with tempfile.TemporaryDirectory() as td:
   allow=Path(td)/'.video_translation_test_user'; allow.write_text('99')
   env={'os':os,'OWNER_ID':42,'DB_PATH':str(Path(td)/'subs.db')}
   exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<allow>','exec'),env)
   with patch.dict(os.environ,{},clear=True):
    self.assertTrue(env['_can_run_translation_test'](99))
    self.assertFalse(env['_can_run_translation_test'](98))
    allow.unlink()
    self.assertFalse(env['_can_run_translation_test'](99))

 async def test_test_allowlist_accepts_only_configured_account_or_owner(self):
  import os
  from unittest.mock import patch
  tree=ast.parse(patched_source(include_owner=True))
  fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_can_run_translation_test')
  env={'os':os,'OWNER_ID':42}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<allowlist>','exec'),env)
  with patch.dict(os.environ,{'VIDEO_TRANSLATION_TEST_USER_ID':'99'}):
   self.assertTrue(env['_can_run_translation_test'](42))
   self.assertTrue(env['_can_run_translation_test'](99))
   self.assertFalse(env['_can_run_translation_test'](98))
  with patch.dict(os.environ,{'VIDEO_TRANSLATION_TEST_USER_ID':'99,98'}):
   self.assertFalse(env['_can_run_translation_test'](99))

 async def test_explicitly_configured_test_account_can_start(self):
  tree=ast.parse(patched_source(include_owner=True))
  fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='cmd_owner_translation_sync_test')
  env={'Update':object,'ContextTypes':SimpleNamespace(DEFAULT_TYPE=object),'OWNER_ID':42,
       '_can_run_translation_test':lambda user_id:user_id in (42,99), '_clear_transient_flows':lambda c:None}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<command>','exec'),env)
  message=SimpleNamespace(reply_text=AsyncMock()); context=SimpleNamespace(user_data={})
  await env['cmd_owner_translation_sync_test'](SimpleNamespace(effective_user=SimpleNamespace(id=99),effective_message=message),context)
  self.assertTrue(context.user_data.get('video_translation_lipsync_test'))

 async def test_non_owner_cannot_enable_paid_test(self):
  tree=ast.parse(patched_source(include_owner=True))
  fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='cmd_owner_translation_sync_test')
  env={'Update':object,'ContextTypes':SimpleNamespace(DEFAULT_TYPE=object),'OWNER_ID':42,'_can_run_translation_test':lambda user_id:user_id == 42}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<command>','exec'),env)
  message=SimpleNamespace(reply_text=AsyncMock())
  context=SimpleNamespace(user_data={})
  await env['cmd_owner_translation_sync_test'](SimpleNamespace(effective_user=SimpleNamespace(id=99),effective_message=message),context)
  self.assertNotIn('video_translation_lipsync_test',context.user_data)
  message.reply_text.assert_awaited_once()

 async def test_owner_translation_sends_dubbed_video_through_lipsync(self):
  tree=ast.parse(patched_source(include_owner=True))
  fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_run_video_translation')
  sync=AsyncMock(return_value=b'synchronized')
  reply=AsyncMock()
  env={'asyncio':asyncio,'Update':object,'ContextTypes':SimpleNamespace(DEFAULT_TYPE=object),
   'OWNER_ID':42,'_can_run_translation_test':lambda user_id:user_id == 42,'OPENAI_STT_KEY':'set','OPENAI_TTS_KEY':'set',
   '_generated_video_duration_seconds_sync':lambda _:5.0,'_extract_video_audio_sync':lambda _:b'audio',
   '_stt_transcribe_bytes':AsyncMock(return_value='Привет'), 'ask_openai_text':AsyncMock(return_value='Hello'),
   '_split_tts_text':lambda t,n:[t], 'TTS_MAX_CHARS':1000,'_tts_bytes_sync':lambda *args:b'voice',
   '_avatar_tts_voice_get':lambda _:None,'_concat_audio_mp3_sync':lambda xs:b'voice',
   '_mux_translated_audio_sync':lambda *args:b'dubbed', '_reply_video_bytes':reply,
   '_sync_owner_translated_video':sync,'log':SimpleNamespace(exception=lambda *a,**k:None)}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<translation>','exec'),env)
  message=SimpleNamespace(reply_text=AsyncMock())
  update=SimpleNamespace(effective_message=message,effective_user=SimpleNamespace(id=42))
  context=SimpleNamespace(user_data={'video_translation_lipsync_test':True})
  result=await env['_run_video_translation'](update,context,b'original','English')
  self.assertTrue(result)
  sync.assert_awaited_once_with(b'dubbed',5.0)
  self.assertEqual(reply.await_args.args[1],b'synchronized')
  self.assertNotIn('video_translation_lipsync_test',context.user_data)
