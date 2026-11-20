import ast, asyncio, json, logging, subprocess, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
ROOT = Path(__file__).resolve().parents[1]

class TestNoDuplicateKling(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'main.py'
            p.write_bytes((ROOT / 'main.py').read_bytes())
            for patch in ('main_kling_billing_failures.patch', 'main_kling_no_duplicate.patch'):
                subprocess.run(['patch', '--batch', '-p1', '-i', str(ROOT / 'ops' / patch)], cwd=tmp, check=True, stdout=subprocess.DEVNULL)
            tree = ast.parse(p.read_text())
        func = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_create_and_poll_i2v')
        self.ns = {'__name__':'test', 'time':time, 'json':json, 'asyncio':asyncio, 'log':logging.getLogger('test'), 'Update':object, 'ContextTypes':SimpleNamespace(DEFAULT_TYPE=object), '_extract_first_url':lambda v:None, '_api_error_preview':lambda r:'', 'LUMA_MAX_WAIT_S':10, 'RUNWAY_MAX_WAIT_S':10}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0),func], type_ignores=[])), '<test>', 'exec'), self.ns)
        self.update = SimpleNamespace(effective_message=SimpleNamespace(reply_text=AsyncMock()))
    def run_case(self, post, poll):
        client = SimpleNamespace(post=post)
        class Client:
            async def __aenter__(self): return client
            async def __aexit__(self,*args): pass
        self.ns['httpx'] = SimpleNamespace(AsyncClient=lambda **kw:Client())
        self.ns['_poll_video_task_generic'] = poll
        result = asyncio.run(self.ns['_create_and_poll_i2v'](self.update,'https://example.invalid','key',[('/create',{}),('/alternate',{})],['/task/{id}'],'Kling image→video'))
        return result
    def test_poll_exception_does_not_create_again(self):
        response = SimpleNamespace(status_code=200, json=lambda:{'id':'task123'})
        post = AsyncMock(return_value=response)
        self.assertFalse(self.run_case(post, AsyncMock(side_effect=RuntimeError('connection lost'))))
        self.assertEqual(post.await_count, 1)
        self.assertIn('task123', self.update.effective_message.reply_text.await_args.args[0])
    def test_create_timeout_does_not_create_again(self):
        post = AsyncMock(side_effect=TimeoutError('connection lost'))
        self.assertFalse(self.run_case(post, AsyncMock()))
        self.assertEqual(post.await_count, 1)
        self.assertIn('неизвестен', self.update.effective_message.reply_text.await_args.args[0])
    def test_missing_id_does_not_create_again(self):
        response = SimpleNamespace(status_code=200, json=lambda:{})
        post = AsyncMock(return_value=response)
        self.assertFalse(self.run_case(post, AsyncMock()))
        self.assertEqual(post.await_count, 1)
        self.assertIn('неизвестен', self.update.effective_message.reply_text.await_args.args[0])

    def test_server_error_does_not_create_again(self):
        response = SimpleNamespace(status_code=503)
        post = AsyncMock(return_value=response)
        self.assertFalse(self.run_case(post, AsyncMock()))
        self.assertEqual(post.await_count, 1)
        self.assertIn('неизвестен', self.update.effective_message.reply_text.await_args.args[0])
