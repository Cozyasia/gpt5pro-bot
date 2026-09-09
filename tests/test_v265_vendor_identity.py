import hashlib

import pytest

from neyrobot_prod.v265_vendor_identity import VendorArtifactError, normalize_export, qualification_status


def sample(case, identity=(1.0, 2.0)):
    return {"vendor":"fixture","case":case,"topology":"dense-v1","identity":identity,
            "expression":[0.0],"vertex_count":5255,"source_sha256":hashlib.sha256(case.encode()).hexdigest()}


def test_vendor_export_requires_separate_identity_and_expression():
    payload = sample("case01"); payload["expression"] = []
    with pytest.raises(VendorArtifactError, match="separately"):
        normalize_export(payload, expected_case="case01")


def test_qualification_fails_closed_without_all_frozen_cases():
    artifact = normalize_export(sample("case01"), expected_case="case01")
    result = qualification_status({"case01": artifact})
    assert not result["complete"]
    assert not result["ready_for_geometry_benchmark"]


def test_vendor_export_rejects_sparse_topology():
    payload = sample("case08"); payload["vertex_count"] = 68
    with pytest.raises(VendorArtifactError, match="dense"):
        normalize_export(payload, expected_case="case08")
