# -*- coding: utf-8 -*-
from __future__ import annotations

import inspect
import os
import unittest

from neyrobot_prod import v265_prospective_monotonic_validator as validator


class V265ProspectiveMonotonicValidatorTests(unittest.TestCase):
    def test_validator_is_inert_without_explicit_opt_in(self) -> None:
        old = os.environ.pop("V265_PROSPECTIVE_VALIDATION", None)
        try:
            self.assertFalse(validator._flag())
        finally:
            if old is not None:
                os.environ["V265_PROSPECTIVE_VALIDATION"] = old

    def test_validator_contract_has_exactly_one_gemini_stage1_call_site(self) -> None:
        source = inspect.getsource(validator._run)
        self.assertEqual(source.count("v265._call_google("), 1)
        self.assertIn("gemini_calls=1", source)
        self.assertIn("immutable=true", source)
        self.assertIn("standard_pre", source)
        self.assertIn("standard_post", source)
        self.assertIn("strict_pre", source)
        self.assertIn("strict_post", source)

    def test_validator_does_not_change_hard_thresholds_or_fallbacks(self) -> None:
        source = inspect.getsource(validator)
        for token in (
            "_IDENTITY",
            "_EYE_ERROR",
            "_INTEROCULAR",
            "_NOSE_MOUTH",
            "_INNER_FACE",
            "legacy_fallback=true",
            "provider_rescue=true",
        ):
            self.assertNotIn(token, source)
        self.assertIn("v265.production_gate", source)
        self.assertIn("legacy_fallback=false", source)
        self.assertIn("same_dense68_engine=true", source)

    def test_historical_source_recovery_requires_logged_exact_signature(self) -> None:
        self.assertEqual(validator._EXPECTED_SOURCE_BYTES, 121684)
        self.assertEqual(validator._EXPECTED_SOURCE_DIMS, (960, 1280))
        self.assertEqual(validator._EXPECTED_SOURCE_FACE, (189, 342, 516, 710))
        self.assertEqual(validator._EXPECTED_EXPRESSION_BYTES, 447707)

    def test_old_and_new_selection_are_separate_analysis_paths(self) -> None:
        run_source = inspect.getsource(validator._run)
        self.assertIn("_old_selection(", run_source)
        self.assertIn("_new_selection(", run_source)
        new_source = inspect.getsource(validator._new_selection)
        self.assertIn("_select_ocular_candidate", new_source)
        self.assertIn("_final_candidate_decision", new_source)


if __name__ == "__main__":
    unittest.main()
