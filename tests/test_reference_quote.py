import unittest

from neyrobot_prod.reference_quote import quote_reference_job
from neyrobot_prod.reference_studio import ProviderCapabilities, ReferenceKind


class ReferenceQuoteTests(unittest.TestCase):
    def setUp(self):
        self.providers = (ProviderCapabilities(
            "verified", image_to_video=True,
            real_person_reference=True, max_seconds=10,
        ),)

    def test_missing_price_blocks_billable_job(self):
        result = quote_reference_job(
            ReferenceKind.REAL_PERSON, self.providers,
            seconds=8, consent_confirmed=True,
        )
        self.assertFalse(result.allowed)
        self.assertIsNone(result.credits)

    def test_quoted_price_rounds_up(self):
        result = quote_reference_job(
            ReferenceKind.REAL_PERSON, self.providers,
            seconds=8, consent_confirmed=True,
            verified_credits_per_second={"verified": "1.25"},
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.credits, 10)

    def test_bad_price_and_rejection_block(self):
        for rate in ("0", "-2", "nan", "inf", "not-a-rate"):
            with self.subTest(rate=rate):
                result = quote_reference_job(
                    ReferenceKind.REAL_PERSON, self.providers,
                    seconds=8, consent_confirmed=True,
                    verified_credits_per_second={"verified": rate},
                )
                self.assertFalse(result.allowed)
        rejected = quote_reference_job(
            ReferenceKind.REAL_PERSON, self.providers,
            seconds=8, consent_confirmed=True, previously_rejected=True,
            verified_credits_per_second={"verified": "1"},
        )
        self.assertFalse(rejected.allowed)


if __name__ == "__main__":
    unittest.main()
