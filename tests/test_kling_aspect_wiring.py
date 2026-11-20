import ast, asyncio, logging, subprocess, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
class TestWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'main.py';p.write_bytes((ROOT/'main.py').read_bytes())
            for name in ('main_kling_billing_failures.patch','main_promo_attempts_v1.patch','main_kling_no_duplicate.patch','main_kling_aspect_delivery.patch'):
                subprocess.run(['patch','--batch','-p1','-i',str(ROOT/'ops'/name)],cwd=tmp,check=True,stdout=subprocess.DEVNULL)
            cls.source=p.read_text();tree=ast.parse(cls.source)
        cls.nodes={n.name:n for n in tree.body if isinstance(n,ast.AsyncFunctionDef)}
    def test_aspect_forwarded_only_from_kling_i2v(self):
        body=ast.unparse(self.nodes['_run_comet_i2v'])
        self.assertIn('target_aspect=aspect',body)
        self.assertEqual(body.count('target_aspect=aspect'),1)
        self.assertIn('target_aspect=target_aspect',ast.unparse(self.nodes['_create_and_poll_i2v']))
        self.assertEqual(ast.unparse(self.nodes['_poll_video_task_generic']).count('target_aspect=target_aspect'),2)
    def test_failed_conversion_returns_original_and_warning(self):
        node=self.nodes['_fit_kling_delivery']
        ns={'asyncio':asyncio,'log':logging.getLogger('test')}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<test>','exec'),ns)
        with patch('neyrobot_prod.kling_aspect_delivery.normalize_kling_video',side_effect=ValueError('bad')):
            content,caption=asyncio.run(ns['_fit_kling_delivery'](b'video','caption','9:16'))
        self.assertEqual(content,b'video');self.assertIn('отправлен оригинал',caption)
