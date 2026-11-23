import ast,unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from test_seedance_aspect_selection import patched_source

class KlingOptionTests(unittest.IsolatedAsyncioTestCase):
 def callback(self):
  tree=ast.parse(patched_source())
  fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_on_kling_video_option')
  class BadRequest(Exception): pass
  env={'BadRequest':BadRequest, '_kling_video_options_keyboard':lambda context:'keyboard'}
  code=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),fn],type_ignores=[])
  exec(compile(ast.fix_missing_locations(code),'<callback>','exec'),env)
  return env['_on_kling_video_option'],BadRequest
 async def test_same_value_does_not_emit_error(self):
  fn,error=self.callback(); msg=SimpleNamespace(edit_reply_markup=AsyncMock(side_effect=error('Message is not modified')))
  q=SimpleNamespace(data='tvopt:dur:5',answer=AsyncMock(),message=msg)
  ctx=SimpleNamespace(user_data={'awaiting_text_video_prompt':True,'text_video_engine':'kling','kling_text_duration':5})
  await fn(SimpleNamespace(callback_query=q),ctx)
  self.assertEqual(ctx.user_data['kling_text_duration'],5)
 async def test_other_telegram_errors_propagate(self):
  fn,error=self.callback(); msg=SimpleNamespace(edit_reply_markup=AsyncMock(side_effect=error('message cannot be edited')))
  q=SimpleNamespace(data='tvopt:dur:5',answer=AsyncMock(),message=msg)
  ctx=SimpleNamespace(user_data={'awaiting_text_video_prompt':True,'text_video_engine':'kling'})
  with self.assertRaises(error): await fn(SimpleNamespace(callback_query=q),ctx)
