import unittest
from neyrobot_prod.marketplace_studio import ProductProject, Stage, Output, Marketplace, select_output, select_marketplace, add_references, continue_after_references
from neyrobot_prod.marketplace_navigation import back, cancel

class MarketplaceNavigationTests(unittest.TestCase):
    def test_back_keeps_uploaded_photos_from_brief(self):
        p = select_marketplace(select_output(ProductProject(), Output.COMPLETE), Marketplace.OZON)
        p = continue_after_references(add_references(p, ('a',)))
        self.assertEqual(back(p).reference_ids, ('a',))
        self.assertEqual(back(p).stage, Stage.REFERENCES)
    def test_cancel_resets(self):
        self.assertEqual(cancel(), ProductProject())

if __name__ == '__main__':
    unittest.main()
