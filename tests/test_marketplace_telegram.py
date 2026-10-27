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
    def test_preview_available_only_after_confirmation(self):
        from neyrobot_prod.marketplace_studio import set_brief, confirm_attributes
        from neyrobot_prod.marketplace_telegram import buttons
        p = ProductProject(stage=Stage.BRIEF, reference_ids=('ref',))
        p = confirm_attributes(set_brief(p, 'Фарфоровая кружка'))
        self.assertIn(('Проверить задание', 'mp:preview'), buttons(p))
        self.assertEqual(apply_action(p, 'preview'), p)
        with self.assertRaises(ValueError):
            apply_action(ProductProject(), 'preview')

    def test_unavailable_generation_cannot_finish(self):
        from neyrobot_prod.marketplace_studio import set_brief, confirm_attributes
        p = ProductProject(stage=Stage.BRIEF, reference_ids=('ref',))
        p = confirm_attributes(set_brief(p, 'Кружка'))
        with self.assertRaisesRegex(ValueError, 'Генерация'):
            apply_action(p, 'finish')

    def test_back(self):
        p = apply_action(ProductProject(), 'output:photos')
        self.assertEqual(apply_action(p, 'back').stage, Stage.OUTPUT)

if __name__ == '__main__':
    unittest.main()
