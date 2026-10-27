import unittest

from neyrobot_prod.marketplace_generation import (
    ensure_paid_generation_ready, prepare_generation, build_product_image_prompt,
)
from neyrobot_prod.marketplace_studio import (
    Output, Marketplace, ProductProject, Stage,
)


class GenerationPreparationTests(unittest.TestCase):
    def test_prepares_confirmed_request(self):
        project = ProductProject(
            output=Output.PHOTOS,
            marketplace=Marketplace.OZON,
            stage=Stage.APPROVAL,
            reference_ids=("file_1", "file_2"),
            brief="Фарфоровая чашка",
            attributes_confirmed=True,
        )
        request = prepare_generation(project)
        self.assertEqual(request.marketplace, "ozon")
        self.assertEqual(request.reference_file_ids, ("file_1", "file_2"))
        self.assertEqual(request.brief, "Фарфоровая чашка")

    def test_grounded_image_prompt(self):
        p = ProductProject(output=Output.INFOGRAPHICS, marketplace=Marketplace.OZON,
                           stage=Stage.APPROVAL, reference_ids=('ref1',),
                           brief='Фарфор, 250 мл', attributes_confirmed=True)
        prompt = build_product_image_prompt(prepare_generation(p))
        self.assertIn('Ozon', prompt)
        self.assertIn('Фарфор, 250 мл', prompt)
        self.assertIn('Не придумывай', prompt)
        self.assertIn('инфографику', prompt)

    def test_video_cannot_use_image_prompt(self):
        p = ProductProject(output=Output.VIDEO, marketplace=Marketplace.OZON,
                           stage=Stage.APPROVAL, reference_ids=('ref1',),
                           brief='Кружка', attributes_confirmed=True)
        with self.assertRaises(ValueError):
            build_product_image_prompt(prepare_generation(p))

    def test_refuses_incomplete_request(self):
        with self.assertRaises(ValueError):
            prepare_generation(ProductProject())
        with self.assertRaises(ValueError):
            prepare_generation(ProductProject(stage=Stage.APPROVAL, attributes_confirmed=True))

    def test_refuses_unpriced_or_unapproved_paid_generation(self):
        with self.assertRaises(RuntimeError):
            ensure_paid_generation_ready(provider_enabled=False, quoted_credits=10, quote_accepted=True)
        with self.assertRaises(ValueError):
            ensure_paid_generation_ready(provider_enabled=True, quoted_credits=None, quote_accepted=True)
        with self.assertRaises(ValueError):
            ensure_paid_generation_ready(provider_enabled=True, quoted_credits=10, quote_accepted=False)
        self.assertIsNone(ensure_paid_generation_ready(provider_enabled=True, quoted_credits=10, quote_accepted=True))


if __name__ == "__main__":
    unittest.main()
