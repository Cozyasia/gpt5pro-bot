"""Regression: approving a Suno song is a pending state, not a failed clip."""
import ast
from pathlib import Path
import unittest


class MusicVideoAudioReviewTest(unittest.TestCase):
    def test_audio_review_returns_pending_not_false(self):
        source = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        start = next(node for node in module.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_start_vocal_clip")
        job = next(node for node in start.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_job")
        review = next(node for node in ast.walk(job) if isinstance(node, ast.Return)
                      and node.lineno > 1
                      and "Audio review is a pending user decision" in "\n".join(source.splitlines()[max(0, node.lineno-5):node.lineno]))
        self.assertIsInstance(review.value, ast.Constant)
        self.assertIsNone(review.value.value)


if __name__ == "__main__":
    unittest.main()
