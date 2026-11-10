import unittest

from presentation_studio import _extract_brand_name_regex, _extract_slide_count, _fallback_structure


class ShortPresentationDeckTests(unittest.TestCase):
    def test_topic_and_requested_three_slides_are_preserved(self):
        brief = 'Тестовая презентация: «Осенние листья». 3 слайда: причины, пигменты, вывод.'
        self.assertEqual(_extract_brand_name_regex(brief), 'Осенние листья')
        self.assertEqual(_extract_slide_count(brief), 3)
        project = {"raw_brief": brief, "profile": {"brand_name": "Осенние листья", "requested_slide_count": 3}}
        structure = _fallback_structure(project)
        self.assertEqual(len(structure), 3)
        self.assertEqual(structure[0]["title"], "Осенние листья")
        self.assertEqual(structure[-1]["title"], "Вывод")
