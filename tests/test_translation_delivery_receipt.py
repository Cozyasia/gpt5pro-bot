import ast,unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from test_seedance_aspect_selection import patched_source

class DeliveryReceiptTests(unittest.IsolatedAsyncioTestCase):
 def build(self,duplicate):
  tree=ast.parse(patched_source(include_owner=True))
  fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_reply_video_bytes')
  env={'Update':object,'BytesIO':BytesIO,'_video_result_key':lambda *a,**k:'key',
       '_mark_video_sent_once':lambda _:duplicate,'_claim_kling_video_delivery':AsyncMock(),
       'VIDEO_RESULT_SEND_AS_DOCUMENT':False,'VIDEO_SEND_WRITE_TIMEOUT_S':30,
       'InputFile':lambda f:f,'log':SimpleNamespace(info=lambda *a:None,warning=lambda *a:None)}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<delivery>','exec'),env)
  return env['_reply_video_bytes']
 async def test_success_returns_explicit_receipt(self):
  msg=SimpleNamespace(reply_video=AsyncMock())
  result=await self.build(False)(SimpleNamespace(effective_chat=SimpleNamespace(id=1),effective_message=msg),b'x'*600,'done')
  self.assertIs(result,True);msg.reply_video.assert_awaited_once()
 async def test_suppressed_duplicate_is_not_delivery_receipt(self):
  msg=SimpleNamespace(reply_video=AsyncMock())
  result=await self.build(True)(SimpleNamespace(effective_chat=SimpleNamespace(id=1),effective_message=msg),b'x'*600,'done')
  self.assertIs(result,False);msg.reply_video.assert_not_awaited()
 async def test_delivery_timeout_is_not_reported_as_success(self):
  msg=SimpleNamespace(reply_video=AsyncMock(side_effect=TimeoutError()))
  with self.assertRaises(TimeoutError):
   await self.build(False)(SimpleNamespace(effective_chat=SimpleNamespace(id=1),effective_message=msg),b'x'*600,'done')
