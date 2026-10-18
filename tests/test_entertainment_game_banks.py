import unittest
from neyrobot_prod.entertainment.games import GAME_BANKS, start, current_question, answer, next_round

class GameBanksTests(unittest.TestCase):
    def test_all_banks_complete(self):
        for game_id, questions in GAME_BANKS.items():
            self.assertEqual(len(questions), 5)
            session = start(game_id)
            for question in questions:
                self.assertEqual(len(question.answers), 4)
                self.assertIn(question.correct, "abcd")
                self.assertEqual(current_question(session), question)
                session, correct = answer(session, question.correct)
                self.assertTrue(correct)
                session = next_round(session)
            self.assertTrue(session.finished)
            self.assertEqual(session.score, 5)

if __name__ == "__main__":
    unittest.main()
