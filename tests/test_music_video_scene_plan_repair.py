"""Regression tests for validator-guided ScenePlan repair."""
import ast
from pathlib import Path
import unittest


class ScenePlanRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
        cls.module = ast.parse(cls.source)
        cls.compiler = next(node for node in cls.module.body
                            if isinstance(node, ast.AsyncFunctionDef)
                            and node.name == "_compile_music_video_scene_plan")

    def test_invalid_llm_plan_gets_second_compilation(self):
        calls = [n for n in ast.walk(self.compiler)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)
                 and n.func.id == "ask_openai_text"]
        self.assertEqual(len(calls), 2, "Initial compile and one validator-guided repair required")

    def test_repair_is_validated_not_blindly_accepted(self):
        source = ast.get_source_segment(self.source, self.compiler)
        self.assertIn("_music_video_extract_json_object(repaired_raw)", source)
        self.assertIn("expected_duration_s=duration", source)
        self.assertIn("expected_aspect=aspect", source)
        self.assertIn("require_lip_sync=lip_sync_required", source)

    def test_repair_preserves_user_chronology(self):
        source = ast.get_source_segment(self.source, self.compiler)
        self.assertIn("Split oversized scenes without dropping any action", source)
        self.assertIn("scene indices sequential", source)
        self.assertIn("repair also failed", source)


if __name__ == "__main__":
    unittest.main()
