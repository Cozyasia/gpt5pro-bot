import unittest
from neyrobot_prod.translation_segments import plan_segments

class TranslationSegmentTests(unittest.TestCase):
    def test_lengths_cover_video_without_gaps(self):
        for duration in (2, 9.9, 10, 10.1, 11, 21, 59.7, 180):
            spans = plan_segments(duration)
            self.assertAlmostEqual(spans[0][0], 0)
            self.assertAlmostEqual(spans[-1][1], duration)
            for start, end in spans:
                self.assertGreaterEqual(end-start, 2)
                self.assertLessEqual(end-start, 10)
            for a,b in zip(spans,spans[1:]):
                self.assertAlmostEqual(a[1],b[0])

    def test_invalid_durations(self):
        for duration in (0,1.99,180.1,float('nan'),float('inf')):
            with self.assertRaises(ValueError): plan_segments(duration)
