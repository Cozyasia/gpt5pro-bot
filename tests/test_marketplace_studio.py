import unittest

from neyrobot_prod.marketplace_studio import (
    Marketplace, Output, ProductProject, Stage, add_references, approve,
    confirm_attributes, continue_after_references, select_marketplace,
    select_output, set_brief, upload_message,
)


class MarketplaceStudioTests(unittest.TestCase):
    def test_complete_intake_requires_explicit_approval(self):
        p = select_output(ProductProject(), Output.COMPLETE)
        p = select_marketplace(p, Marketplace.OZON)
        p = add_references(p, ("photo-1", "photo-2", "photo-1"))
        self.assertEqual(p.reference_ids, ("photo-1", "photo-2"))
        self.assertIn("2/30", upload_message(p))
        p = continue_after_references(p)
        p = set_brief(p, "Чайный сервиз, ручная инфографика")
        p = confirm_attributes(p)
        with self.assertRaises(ValueError):
            approve(p, quote_accepted=False)
        self.assertTrue(approve(p, quote_accepted=True).approved)

    def test_empty_references_blocked(self):
        p = select_marketplace(select_output(ProductProject(), Output.VIDEO), Marketplace.GENERIC)
        with self.assertRaises(ValueError):
            continue_after_references(p)

    def test_upload_cap_and_wrong_stage(self):
        p = select_marketplace(select_output(ProductProject(), Output.PHOTOS), Marketplace.AMAZON)
        with self.assertRaises(ValueError):
            add_references(p, tuple(str(i) for i in range(31)))
        with self.assertRaises(ValueError):
            set_brief(p, "Not ready")


if __name__ == "__main__":
    unittest.main()
