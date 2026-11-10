"""Regression guard for the supported default OpenAI Images model."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OpenAIImageModelCurrentTests(unittest.TestCase):
    def test_main_defaults_to_supported_images_model(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn(
            'os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2.5-sunburst")',
            source,
        )
        tree = ast.parse(source)
        image_model_assignments = [
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "IMAGES_MODEL"
                for target in node.targets
            )
        ]
        self.assertEqual(len(image_model_assignments), 1)

    def test_render_and_sample_do_not_reintroduce_retired_image_model(self):
        for filename in ("render.yaml", "env.sample"):
            source = (ROOT / filename).read_text(encoding="utf-8")
            self.assertNotIn("OPENAI_IMAGE_MODEL=gpt-image-1", source)
            self.assertIn("gpt-image-2.5-sunburst", source)


if __name__ == "__main__":
    unittest.main()
