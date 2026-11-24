import ast,unittest
from pathlib import Path
from types import SimpleNamespace
import subprocess, tempfile, re as _regex
ROOT=Path(__file__).resolve().parents[1]
def patched_source():
 with tempfile.TemporaryDirectory() as td:
  (Path(td)/'main.py').write_bytes((ROOT/'main.py').read_bytes())
  names=_regex.findall(r'patch --batch --forward -p1 < /app/(ops/\S+)', (ROOT/'Dockerfile').read_text())
  names += ['ops/main_kling_delivery_claim.patch','ops/main_kling_finance_recovery.patch','ops/main_kling_background.patch','ops/main_continuation_media.patch','ops/main_seedance_aspect.patch','ops/main_seedance_option_ack.patch','ops/main_seedance_model.patch','ops/main_kling_options_idempotent.patch','ops/main_lipsync_route_priority.patch']
  names=list(dict.fromkeys(names))
  for name in names:
   path=ROOT/name
   if not path.exists(): continue
   result=subprocess.run(['patch','--batch','--forward','-p1','-i',str(path)],cwd=td,capture_output=True)
   if name in ('ops/main_continuation_media.patch','ops/main_seedance_aspect.patch','ops/main_seedance_option_ack.patch','ops/main_seedance_model.patch','ops/main_kling_options_idempotent.patch','ops/main_lipsync_route_priority.patch') and result.returncode:
    raise RuntimeError('patch failed: '+name)
  return (Path(td)/'main.py').read_text()

class Button:
 def __init__(self,text,callback_data):self.text=text;self.callback_data=callback_data
class TestSeedanceOptions(unittest.TestCase):
 def test_options_offer_all_three_aspects(self):
  tree=ast.parse(patched_source())
  fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_seedance_duration_keyboard')
  env={'InlineKeyboardButton':Button,'InlineKeyboardMarkup':lambda rows:rows}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<kb>','exec'),env)
  rows=env['_seedance_duration_keyboard'](SimpleNamespace(user_data={'seedance_text_duration':4,'seedance_text_aspect':'16:9'}))
  buttons=[b for row in rows for b in row]
  self.assertEqual({b.callback_data for b in buttons if b.callback_data.startswith('seedance_aspect:')},{'seedance_aspect:9:16','seedance_aspect:16:9','seedance_aspect:1:1'})
  self.assertTrue(any('✅' in b.text and '16:9' in b.text for b in buttons))

class TestSeedanceRouting(unittest.IsolatedAsyncioTestCase):
 async def test_selection_reaches_generation_and_explicit_prompt_overrides(self):
  import re
  tree=ast.parse(patched_source())
  fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_start_text_video')
  for i,node in enumerate(fn.body):
   if isinstance(node,ast.If) and ast.unparse(node.test).startswith("engine == 'sora'"):
    fn.body=fn.body[:i]+[ast.Return(value=ast.Tuple(elts=[ast.Name(id='duration',ctx=ast.Load()),ast.Name(id='aspect',ctx=ast.Load())],ctx=ast.Load()))];break
  future=ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)
  env={'ContextTypes':SimpleNamespace(DEFAULT_TYPE=object),'Update':object,'parse_video_opts':lambda prompt:(5,'16:9'),'TEXT_VIDEO_DEFAULT_ENGINE':'kling','TEXT_VIDEO_ALLOW_RUNWAY':True,'re':re}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[future,fn],type_ignores=[])),'<route>','exec'),env)
  ctx=SimpleNamespace(user_data={'text_video_engine':'seedance','seedance_text_duration':4,'seedance_text_aspect':'1:1'})
  self.assertEqual(await env['_start_text_video'](None,ctx,'A tropical beach'),(4,'1:1'))
  self.assertEqual(await env['_start_text_video'](None,ctx,'A beach in 16:9'),(4,'16:9'))
  self.assertEqual(await env['_start_text_video'](None,ctx,'Пляж, 15 секунд'),(15,'1:1'))

class TestSeedanceCallback(unittest.IsolatedAsyncioTestCase):
 async def test_aspect_button_updates_active_selection(self):
  import contextlib
  from unittest.mock import AsyncMock
  tree=ast.parse(patched_source())
  fn=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='_on_seedance_aspect_callback')
  class Stop(Exception):pass
  keyboard=lambda ctx:ctx.user_data['seedance_text_aspect']
  env={'ApplicationHandlerStop':Stop,'contextlib':contextlib,'_seedance_duration_keyboard':keyboard}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<callback>','exec'),env)
  msg=SimpleNamespace(edit_reply_markup=AsyncMock(), reply_text=AsyncMock())
  query=SimpleNamespace(data='seedance_aspect:16:9',answer=AsyncMock(),message=msg)
  ctx=SimpleNamespace(user_data={'awaiting_text_video_prompt':True,'text_video_engine':'seedance'})
  with self.assertRaises(Stop):await env['_on_seedance_aspect_callback'](SimpleNamespace(callback_query=query),ctx)
  self.assertEqual(ctx.user_data['seedance_text_aspect'],'16:9')
  msg.edit_reply_markup.assert_awaited_once_with(reply_markup='16:9')
  self.assertIn('16:9', msg.reply_text.await_args.args[0])

class TestSeedanceDefaultModel(unittest.TestCase):
 def test_default_model_matches_provider_catalog(self):
  source=patched_source()
  tree=ast.parse(source)
  assignment=next(node for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='SEEDANCE_MODEL' for target in node.targets))
  import os
  from unittest.mock import patch
  env={'os':os}
  with patch.dict(os.environ,{},clear=True):
   exec(compile(ast.fix_missing_locations(ast.Module(body=[assignment],type_ignores=[])),'<config>','exec'),env)
  self.assertEqual(env['SEEDANCE_MODEL'],'seedance-2-5')
