import unittest
from neyrobot_prod.video_overlay_layout import SafeArea, safe_rectangle, layout_editorial_text

class OverlayLayoutTests(unittest.TestCase):
    def test_inside_frame(self):
        for width, height in [(720, 1280), (1080, 1920)]:
            x, y, w, h = safe_rectangle(width, height)
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + w, width)
            self.assertLessEqual(y + h, height)
            for b in layout_editorial_text("Заголовок", "Субтитры", width=width, height=height):
                self.assertGreaterEqual(b.x, x)
                self.assertGreaterEqual(b.y, y)
                self.assertLessEqual(b.x + b.width, x + w)
                self.assertLessEqual(b.y + b.height, y + h)

    def test_empty_is_not_rendered(self):
        self.assertEqual(layout_editorial_text("", ""), [])

    def test_invalid_margins(self):
        with self.assertRaises(ValueError):
            SafeArea(top=0.6)

if __name__ == "__main__":
    unittest.main()
