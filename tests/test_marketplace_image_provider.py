import base64
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from neyrobot_prod.marketplace_generation import GenerationRequest
from neyrobot_prod.marketplace_image_provider import ReferenceImage, generate_product_image
from neyrobot_prod.marketplace_studio import Output


class ProductImageProviderTests(unittest.TestCase):
    def setUp(self):
        self.request = GenerationRequest(Output.PHOTOS, "ozon", ("photo1",), "Фарфоровая чашка")
        self.references = (ReferenceImage("photo.jpg", b"jpeg data"),)

    def test_sends_reference_to_image_edit_and_decodes_result(self):
        client = Mock()
        client.images.edit.return_value = SimpleNamespace(
            data=[SimpleNamespace(b64_json=base64.b64encode(b"result image").decode())]
        )
        result = generate_product_image(self.request, self.references, client=client)
        self.assertEqual(result, b"result image")
        kwargs = client.images.edit.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-image-1")
        self.assertEqual(kwargs["image"][0].getvalue(), b"jpeg data")
        self.assertIn("Фарфоровая чашка", kwargs["prompt"])
        client.images.generate.assert_not_called()

    def test_refuses_missing_and_mismatched_references(self):
        client = Mock()
        with self.assertRaises(ValueError):
            generate_product_image(self.request, (), client=client)
        with self.assertRaises(ValueError):
            generate_product_image(self.request, (self.references[0], self.references[0]), client=client)
        client.images.edit.assert_not_called()

    def test_refuses_video_and_missing_result(self):
        client = Mock()
        video = GenerationRequest(Output.VIDEO, "ozon", ("photo1",), "Чашка")
        with self.assertRaises(ValueError):
            generate_product_image(video, self.references, client=client)
        client.images.edit.return_value = SimpleNamespace(data=[])
        with self.assertRaises(RuntimeError):
            generate_product_image(self.request, self.references, client=client)


if __name__ == "__main__":
    unittest.main()
