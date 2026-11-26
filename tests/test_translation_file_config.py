import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from neyrobot_prod import translation_telegram_flow as flow

class FileConfigTests(unittest.TestCase):
 def test_scoped_file_enables_only_one_user_and_supplies_prices(self):
  with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'DB_PATH':root+'/db.sqlite'}, clear=True):
   config={'user_id':12,'prices':{key:0.01 for key in flow.PRICE_KEYS}}
   Path(root,'translation_quoted_test.json').write_text(json.dumps(config))
   self.assertTrue(flow.enabled_for_user(12))
   self.assertFalse(flow.enabled_for_user(13))
   self.assertEqual(flow._rates(), config['prices'])
   self.assertTrue(flow._restricted_test_mode())
 def test_invalid_or_incomplete_file_fails_closed(self):
  with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'DB_PATH':root+'/db.sqlite'}, clear=True):
   path=Path(root,'translation_quoted_test.json')
   for content in ('{', json.dumps({'user_id':12,'prices':{}}), json.dumps({'user_id':12,'prices':{key:-1 for key in flow.PRICE_KEYS}})):
    path.write_text(content)
    self.assertFalse(flow.enabled_for_user(12))
 def test_environment_controls_keep_precedence(self):
  with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'DB_PATH':root+'/db.sqlite','TRANSLATION_QUOTED_TEST_USER_IDS':'15'}, clear=True):
   Path(root,'translation_quoted_test.json').write_text(json.dumps({'user_id':12,'prices':{key:0.01 for key in flow.PRICE_KEYS}}))
   self.assertTrue(flow.enabled_for_user(15))
   self.assertFalse(flow.enabled_for_user(12))
