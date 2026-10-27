import unittest
from neyrobot_prod.marketplace_studio import ProductProject, Stage
from neyrobot_prod.marketplace_telegram import apply_action, buttons, load, save

class MarketplaceTelegramTests(unittest.TestCase):
    def test_intake_and_save(self):
        p = apply_action(ProductProject(), 'output:complete')
        p = apply_action(p, 'market:ozon')
        self.assertEqual(p.stage, Stage.REFERENCES)
        data = {}
        save(data, p)
        self.assertEqual(load(data), p)
        self.assertIn(('Продолжить', 'mp:continue'), buttons(p))
    def test_back(self):
        p = apply_action(ProductProject(), 'output:photos')
        self.assertEqual(apply_action(p, 'back').stage, Stage.OUTPUT)

if __name__ == '__main__':
    unittest.main()
