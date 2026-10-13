import unittest

from neyrobot_prod.veo_multiscene import plan_video, estimated_provider_cost_usd


class MultiSceneTests(unittest.TestCase):
    def test_exact_timelines(self):
        for duration, count in [(8, 1), (15, 2), (30, 4), (60, 8)]:
            scenes = plan_video(duration, "Привет это тест русской озвучки")
            self.assertEqual(len(scenes), count)
            self.assertEqual(scenes[0].timeline_start, 0)
            self.assertEqual(scenes[-1].timeline_end, duration)
            self.assertTrue(all(s.generated_seconds == 8 for s in scenes))

    def test_no_lost_words(self):
        script = "один два три четыре пять шесть семь"
        scenes = plan_video(30, script)
        self.assertEqual(" ".join(s.spoken_text for s in scenes), script)

    def test_reject_long_script(self):
        with self.assertRaises(ValueError):
            plan_video(8, "слово " * 17)

    def test_reject_unknown_duration(self):
        with self.assertRaises(ValueError):
            plan_video(20, "Тест")

    def test_cost_counts_generated_not_trimmed_seconds(self):
        self.assertEqual(estimated_provider_cost_usd(15, 0.1), 1.6)


if __name__ == "__main__":
    unittest.main()
