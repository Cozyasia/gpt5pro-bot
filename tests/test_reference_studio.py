import unittest

from neyrobot_prod.reference_studio import (
    ProviderCapabilities, ReferenceKind, decide_reference_route,
)


class ReferenceRoutingTests(unittest.TestCase):
    def test_no_verified_person_capability_fails_closed(self):
        providers = (ProviderCapabilities("seedance", image_to_video=True, max_seconds=30),)
        result = decide_reference_route(
            ReferenceKind.REAL_PERSON, providers, seconds=8, consent_confirmed=True
        )
        self.assertFalse(result.allowed)
        self.assertIsNone(result.provider)

    def test_consent_required_even_with_capability(self):
        providers = (ProviderCapabilities(
            "verified_provider", image_to_video=True,
            real_person_reference=True, max_seconds=10,
        ),)
        self.assertFalse(decide_reference_route(
            ReferenceKind.REAL_PERSON, providers, seconds=8
        ).allowed)
        self.assertTrue(decide_reference_route(
            ReferenceKind.REAL_PERSON, providers, seconds=8, consent_confirmed=True
        ).allowed)

    def test_duration_and_stylized_capabilities(self):
        providers = (ProviderCapabilities(
            "stylized_provider", image_to_video=True,
            stylized_person_reference=True, max_seconds=10,
        ),)
        self.assertFalse(decide_reference_route(
            ReferenceKind.STYLIZED_PERSON, providers, seconds=12
        ).allowed)
        self.assertEqual(decide_reference_route(
            ReferenceKind.STYLIZED_PERSON, providers, seconds=8
        ).provider, "stylized_provider")


if __name__ == "__main__":
    unittest.main()
