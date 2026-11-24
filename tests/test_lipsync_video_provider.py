import ast
import asyncio
import os
import subprocess
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from test_seedance_aspect_selection import patched_source, ROOT

class TestVideoProvider(unittest.IsolatedAsyncioTestCase):
 async def test_video_uses_kling_even_when_heygen_is_configured(self):
  with tempfile.TemporaryDirectory() as td:
   target=Path(td)/'main.py'
   target.write_text(patched_source())
   subprocess.run(['patch','--batch','--forward','-p1','-i',str(ROOT/'ops/main_lipsync_video_provider.patch')],cwd=td,check=True,capture_output=True)
   tree=ast.parse(target.read_text())
  fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_direct_lipsync_render')
  kling=AsyncMock(return_value=b'video'); heygen=AsyncMock()
  env=dict(asyncio=asyncio,os=os,BytesIO=BytesIO,Update=object,ContextTypes=SimpleNamespace(DEFAULT_TYPE=object),
   _direct_lipsync_first_frame_sync=lambda video:b'frame',_direct_lipsync_normalize_audio_sync=lambda audio,ext:audio,
   _direct_lipsync_duration_sync=lambda data,ext:5.,KLING_LIPSYNC_ENABLED=True,KLING_API_KEY='',COMET_API_KEY='key',
   _provider_input_url_from_bytes=lambda data,name:'https://example.invalid/'+name,
   _run_kling_lipsync_result_bytes=kling,VOCAL_CLIP_KLING_MAX_WAIT_S=100,
   _direct_lipsync_mux_audio_sync=lambda video,audio,duration:video,InputFile=lambda bio:bio,
   _direct_lipsync_clear=Mock(),create_image_audio_video=heygen,log=Mock())
  exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<route>','exec'),env)
  message=SimpleNamespace(reply_text=AsyncMock(),reply_video=AsyncMock())
  ctx=SimpleNamespace(user_data={'direct_lipsync_video_bytes':b'video'})
  with patch.dict(os.environ,{'HEYGEN_API_KEY':'configured'}):
   await env['_direct_lipsync_render'](SimpleNamespace(effective_message=message),ctx,b'audio','voice.mp3')
  kling.assert_awaited_once(); heygen.assert_not_awaited(); message.reply_video.assert_awaited_once()
