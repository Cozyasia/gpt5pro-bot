import unittest
from neyrobot_prod.marketplace_studio import Stage
from neyrobot_prod.marketplace_telegram import start_project, clear_project, is_active, load, apply_action

class MarketplaceSessionTests(unittest.TestCase):
    def test_session_lifecycle(self):
        data = {}
        start_project(data)
        self.assertTrue(is_active(data, Stage.OUTPUT))
        self.assertFalse(is_active(data, Stage.BRIEF))
        clear_project(data)
        self.assertFalse(is_active(data))
    def test_cancel_resets_stage(self):
        p = start_project({})
        p = apply_action(p, 'output:photos')
        self.assertEqual(apply_action(p, 'cancel').stage, Stage.OUTPUT)

if __name__ == '__main__':
    unittest.main()
