import ast
from pathlib import Path
import unittest


MAIN = Path(__file__).resolve().parents[1] / "main.py"


class Button:
    def __init__(self, text, callback_data):
        self.text = text
        self.callback_data = callback_data


class Markup:
    def __init__(self, rows):
        self.rows = rows


class MusicVideoMenuTests(unittest.TestCase):
    def test_instrumental_song_uses_non_vocal_video_pipeline(self):
        tree = ast.parse(MAIN.read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_clip_wants_vocals")
        ns = {"re": __import__("re")}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(MAIN), "exec"), ns)
        self.assertFalse(ns["_clip_wants_vocals"]("Инструментальная песня без вокала, 60 секунд"))
        self.assertTrue(ns["_clip_wants_vocals"]("Женщина поёт, мужчина поёт, припев вместе"))

    def test_uploaded_photo_has_one_unified_clip_action_and_keeps_selfie(self):
        tree = ast.parse(MAIN.read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "photo_quick_actions_kb")
        ns = {"InlineKeyboardMarkup": Markup, "InlineKeyboardButton": Button}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(MAIN), "exec"), ns)
        buttons = [button for row in ns["photo_quick_actions_kb"]().rows for button in row]
        clip_buttons = [b for b in buttons if b.callback_data in ("pedit:photoclip", "pedit:vocalclip")]
        self.assertEqual(1, len(clip_buttons))
        self.assertEqual("🎤 AI-видеоклип / песня", clip_buttons[0].text)
        self.assertEqual("pedit:photoclip", clip_buttons[0].callback_data)
        self.assertTrue(any(b.callback_data == "pedit:aiselfie" for b in buttons))


if __name__ == "__main__":
    unittest.main()
