# -*- coding: utf-8 -*-
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import celebrity_selfie_provider_hotfix_v134_1 as hotfix
import celebrity_selfie_v133 as v133


class CelebrityProviderHotfixTests(unittest.TestCase):
    def test_historical_preview_slug_is_normalised_and_filtered(self):
        mod = SimpleNamespace(
            COMET_IMAGE_EDIT_MODEL="gemini-2-5-flash-image-preview",
            COMET_IMAGE_EDIT_FALLBACK_MODELS=["gemini-2.5-flash-image", "gemini-2.5-flash-image-preview"],
        )
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CELEBRITY_COMET_IMAGE_MODELS", None)
            os.environ.pop("CELEBRITY_ALLOW_PREVIEW_IMAGE_MODELS", None)
            models = hotfix._comet_models(mod)
        self.assertEqual(models[0], "gemini-2.5-flash-image")
        self.assertFalse(any("preview" in model for model in models))

    def test_patch_is_installed_into_active_v133_provider(self):
        self.assertIs(v133._comet_models, hotfix._comet_models)
        self.assertEqual(v133.PROVIDER_PATCH_VERSION, hotfix.PATCH_VERSION)

    def test_explicit_stable_models_are_deduplicated(self):
        mod = SimpleNamespace(
            COMET_IMAGE_EDIT_MODEL="gemini-2.5-flash-image",
            COMET_IMAGE_EDIT_FALLBACK_MODELS="gemini-2.5-flash-image,custom-image-model",
        )
        with patch.dict(os.environ, {"CELEBRITY_COMET_IMAGE_MODELS": "gemini-2.5-flash-image"}, clear=False):
            models = hotfix._comet_models(mod)
        self.assertEqual(models.count("gemini-2.5-flash-image"), 1)
        self.assertIn("custom-image-model", models)


if __name__ == "__main__":
    unittest.main()
