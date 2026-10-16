"""Regression: completed Suno is billed before the manual review gate."""
import ast
from pathlib import Path
import unittest


class MusicVideoAudioReviewTest(unittest.TestCase):
    def test_audio_review_commits_only_the_completed_suno_stage(self):
        source = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        start = next(node for node in module.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_start_vocal_clip")
        job = next(node for node in start.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_job")
        review = next(node for node in ast.walk(job) if isinstance(node, ast.Return)
                      and node.lineno > 1
                      and "Suno stage is complete" in "\n".join(source.splitlines()[max(0, node.lineno-5):node.lineno]))
        self.assertIsInstance(review.value, ast.Constant)
        self.assertTrue(review.value.value)


if __name__ == "__main__":
    unittest.main()
