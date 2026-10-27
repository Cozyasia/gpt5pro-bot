import io
import unittest

from PIL import Image

from neyrobot_prod.marketplace_assets import build_infographic


class MarketplaceAssetTests(unittest.TestCase):
    def test_infographic_is_rendered_locally_from_confirmed_russian_brief(self):
        source = io.BytesIO()
        Image.new("RGB", (1024, 1024), "white").save(source, format="PNG")
        result = build_infographic(
            source.getvalue(),
            "Фарфоровая чашка\nОбъём 300 мл\nМожно мыть в посудомоечной машине",
        )
        rendered = Image.open(io.BytesIO(result))
        self.assertEqual(rendered.size, (1024, 1024))
        self.assertNotEqual(result, source.getvalue())


if __name__ == "__main__":
    unittest.main()
