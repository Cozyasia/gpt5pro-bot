"""Kling must never receive Telegram's bot-token-bearing file URL."""
import ast
import unittest
from pathlib import Path

class KlingReferenceSecurityTests(unittest.TestCase):
    def test_kling_reference_uses_prepared_image_on_token_free_host(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text())
        function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == '_run_comet_i2v')
        assignment = next(node for node in ast.walk(function) if isinstance(node, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == 'kling_image_ref' for t in node.targets))
        code = compile(ast.fix_missing_locations(ast.Module(body=[assignment], type_ignores=[])), 'reference', 'exec')
        seen = []
        env = {'img_bytes': b'prepared-image', 'tg_url': 'https://api.telegram.org/file/botSECRET/photo.jpg',
               'data_url': 'data:image/jpeg;base64,example',
               '_provider_input_url_from_bytes': lambda data, name: seen.append(data) or 'https://example.test/provider-input/opaque.jpg'}
        exec(code, env)
        self.assertEqual(seen, [b'prepared-image'])
        self.assertEqual(env['kling_image_ref'], 'https://example.test/provider-input/opaque.jpg')
        self.assertNotIn('SECRET', env['kling_image_ref'])

if __name__ == '__main__': unittest.main()
