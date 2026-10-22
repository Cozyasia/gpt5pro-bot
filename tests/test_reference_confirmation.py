import unittest

from neyrobot_prod.reference_confirmation import stage_reference_approval, approve_reference_job
from neyrobot_prod.reference_quote import ReferenceQuote


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.quote = ReferenceQuote(True, "verified", 10, "ok")
        self.pending = stage_reference_approval(self.quote, user_id=42, seconds=8)

    def test_explicit_approval_required(self):
        self.assertFalse(approve_reference_job(self.pending, user_id=42,
                         token=self.pending.token, current_quote=self.quote, confirmed=False))
        self.assertTrue(approve_reference_job(self.pending, user_id=42,
                        token=self.pending.token, current_quote=self.quote, confirmed=True))

    def test_cross_user_and_stale_quote_rejected(self):
        for user, token, quote in (
            (43, self.pending.token, self.quote),
            (42, "wrong", self.quote),
            (42, self.pending.token, ReferenceQuote(True, "verified", 11, "changed")),
            (42, self.pending.token, ReferenceQuote(False, None, None, "blocked")),
        ):
            with self.subTest(user=user, token=token):
                self.assertFalse(approve_reference_job(
                    self.pending, user_id=user, token=token,
                    current_quote=quote, confirmed=True))

    def test_invalid_quote_cannot_be_staged(self):
        with self.assertRaises(ValueError):
            stage_reference_approval(ReferenceQuote(False, None, None, "blocked"),
                                     user_id=42, seconds=8)


if __name__ == "__main__":
    unittest.main()
