import ast
import pathlib
import unittest
from neyrobot_prod.ad_video_safe_delivery import _auto_caption_color, render_russian_overlay

class AdOverlayModesTests(unittest.TestCase):
    def test_module_parses(self):
        path=pathlib.Path(__file__).resolve().parents[1]/"neyrobot_prod"/"ad_video_safe_delivery.py"
        ast.parse(path.read_text(encoding="utf-8"))
    def test_invalid_mode(self):
        with self.assertRaises(ValueError):
            render_russian_overlay("input.mp4","out.mp4",[(0,1,"Привет")],__file__,text_color="red")
    def test_modes_exist(self):
        self.assertTrue(callable(_auto_caption_color))
        self.assertTrue(callable(render_russian_overlay))
if __name__=="__main__":
    unittest.main()
