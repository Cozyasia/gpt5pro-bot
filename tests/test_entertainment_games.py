"""Regression tests for isolated entertainment game state."""
import unittest
from neyrobot_prod.entertainment.games import start, current_question, answer, next_round, finish, QUIZ

class GameTests(unittest.TestCase):
    def test_correct_answer_increments_score_once(self):
        session = start()
        session, correct = answer(session, current_question(session).correct)
        self.assertTrue(correct)
        self.assertEqual(session.score, 1)
        with self.assertRaises(ValueError):
            answer(session, "a")

    def test_wrong_answer_does_not_score(self):
        session, correct = answer(start(), "a")
        self.assertFalse(correct)
        self.assertEqual(session.score, 0)

    def test_round_requires_answer(self):
        with self.assertRaises(ValueError):
            next_round(start())

    def test_complete_game(self):
        session = start()
        for index in range(len(QUIZ)):
            session, _ = answer(session, QUIZ[index].correct)
            session = next_round(session)
        self.assertTrue(session.finished)
        self.assertEqual(session.score, len(QUIZ))
        self.assertIsNone(current_question(session))

    def test_independent_users(self):
        first = start()
        second = start()
        first, _ = answer(first, "a")
        self.assertFalse(second.answered)
        self.assertEqual(second.score, 0)

    def test_invalid_choice(self):
        with self.assertRaises(ValueError):
            answer(start(), "invalid")

    def test_finish_stops_game(self):
        session = finish(start())
        with self.assertRaises(ValueError):
            answer(session, "a")

if __name__ == "__main__":
    unittest.main()
