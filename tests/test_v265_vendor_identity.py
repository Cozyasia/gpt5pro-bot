import hashlib
import unittest

from neyrobot_prod.v265_vendor_identity import VendorArtifactError, normalize_export, qualification_status


def sample(case, identity=(1.0, 2.0)):
    return {"vendor":"fixture","case":case,"topology":"dense-v1","identity":identity,
            "expression":[0.0],"vertex_count":5255,"source_sha256":hashlib.sha256(case.encode()).hexdigest()}


class VendorIdentityTests(unittest.TestCase):
    def test_vendor_export_requires_separate_identity_and_expression(self):
        payload = sample("case01"); payload["expression"] = []
        with self.assertRaisesRegex(VendorArtifactError, "separately"):
            normalize_export(payload, expected_case="case01")

    def test_qualification_fails_closed_without_all_frozen_cases(self):
        artifact = normalize_export(sample("case01"), expected_case="case01")
        result = qualification_status({"case01": artifact})
        self.assertFalse(result["complete"])
        self.assertFalse(result["ready_for_geometry_benchmark"])

    def test_vendor_export_rejects_sparse_topology(self):
        payload = sample("case08"); payload["vertex_count"] = 68
        with self.assertRaisesRegex(VendorArtifactError, "dense"):
            normalize_export(payload, expected_case="case08")
