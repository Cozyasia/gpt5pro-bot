import ast,re,unittest
from test_seedance_aspect_selection import patched_source

class TestTranslationLanguage(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  tree=ast.parse(patched_source(include_owner=True))
  fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_translation_target_from_caption')
  env={'re':re}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<lang>','exec'),env)
  cls.fn=staticmethod(env['_translation_target_from_caption'])
 def test_unrelated_caption_does_not_become_language(self):
  self.assertEqual(self.fn('Готово: речь синхронизирована с движением рта.'),'Russian')
 def test_test_default_is_english_for_unrelated_caption(self):
  self.assertEqual(self.fn('Готово: речь синхронизирована с движением рта.',default='English'),'English')
 def test_explicit_target_is_detected(self):
  self.assertEqual(self.fn('перевести на английский'),'английский')
  self.assertEqual(self.fn('translate to English'),'English')
