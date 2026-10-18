import unittest
from neyrobot_prod.entertainment.adventures import STORIES, start, scene, choose

class AdventureTests(unittest.TestCase):
    def test_each_adventure_has_reachable_ending(self):
        for story_id in STORIES:
            session = start(story_id)
            for _ in range(5):
                if session.finished:
                    break
                prompt, options, _ = scene(session)
                self.assertTrue(prompt)
                self.assertTrue(options)
                session = choose(session, 0)
            self.assertTrue(session.finished)
            self.assertFalse(scene(session)[1])
    def test_invalid_selection(self):
        with self.assertRaises(ValueError):
            choose(start("detective"), 99)
    def test_unknown_story(self):
        with self.assertRaises(ValueError):
            start("invalid")
    def test_finished_cannot_continue(self):
        session = choose(choose(start("story"), 0), 0)
        self.assertTrue(session.finished)
        with self.assertRaises(ValueError):
            choose(session, 0)
if __name__ == "__main__":
    unittest.main()
