import unittest
import numpy as np
from neyrobot_prod.v265_expression_contract import (
    mouth_decomposition_report,
    source_mouth_identity,
    target_mouth_expression,
)
from tests.test_v265_canonical_semantics import landmarks


class ExpressionContractTests(unittest.TestCase):
    def test_descriptor_separates_opening_from_intrinsic_width(self):
        source = landmarks()
        target = source.copy()
        target[62, 1] -= 3
        target[66, 1] += 3
        self.assertEqual(
            source_mouth_identity(source)["mouth_width"],
            source_mouth_identity(target)["mouth_width"],
        )
        self.assertGreater(
            target_mouth_expression(target)["opening"],
            target_mouth_expression(source)["opening"],
        )

    def test_exact_construct_has_zero_errors_but_texture_stays_unproven(self):
        p = landmarks()
        report = mouth_decomposition_report(p, p, p)
        self.assertEqual(max(report["identity_absolute_error"].values()), 0)
        self.assertEqual(max(report["expression_absolute_error"].values()), 0)
        self.assertTrue(report["target_expression_within_engineering_bound"])
        self.assertFalse(report["mouth_texture_expression_compatible"])
        self.assertFalse(report["expression_disentangled"])

    def test_source_smile_cannot_be_called_target_expression(self):
        source = landmarks()
        target = source.copy()
        target[[48, 54], 1] += 6
        report = mouth_decomposition_report(source, target, source)
        self.assertFalse(report["target_expression_within_engineering_bound"])

    def test_invalid_evidence_fails_closed(self):
        p = landmarks()
        p[36:48] = p[36]
        with self.assertRaises(ValueError):
            target_mouth_expression(p)


if __name__ == "__main__":
    unittest.main()
