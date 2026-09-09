"""Offline-only contract for evaluating commercial L2 identity vendors.

The module deliberately performs no HTTP calls and never accepts a secret. Vendor
outputs are exported by an authorised operator, then normalized and benchmarked
locally. This keeps user photographs and tokens out of CI and prevents an
unlicensed service from becoming a production dependency by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


FROZEN_CASES = ("case01", "case02", "case04", "case05", "case06", "case07", "case08")


class VendorArtifactError(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalIdentityArtifact:
    vendor: str
    case: str
    topology: str
    identity: tuple[float, ...]
    expression: tuple[float, ...]
    vertex_count: int
    source_sha256: str

    @property
    def identity_hash(self) -> str:
        payload = json.dumps(self.identity, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()


def normalize_export(payload: Mapping[str, Any], *, expected_case: str) -> CanonicalIdentityArtifact:
    """Validate the minimum representation required by the L2 geometry bake-off."""
    if expected_case not in FROZEN_CASES:
        raise VendorArtifactError(f"case is not frozen: {expected_case}")
    required = {"vendor", "case", "topology", "identity", "expression", "vertex_count", "source_sha256"}
    missing = sorted(required - payload.keys())
    if missing:
        raise VendorArtifactError(f"missing fields: {', '.join(missing)}")
    if payload["case"] != expected_case:
        raise VendorArtifactError("case mismatch")
    identity = tuple(float(x) for x in payload["identity"])
    expression = tuple(float(x) for x in payload["expression"])
    if not identity or not expression:
        raise VendorArtifactError("identity and expression must be separately exported")
    if int(payload["vertex_count"]) < 468:
        raise VendorArtifactError("topology is not dense enough for the frozen protocol")
    digest = str(payload["source_sha256"])
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
        raise VendorArtifactError("invalid source_sha256")
    return CanonicalIdentityArtifact(
        vendor=str(payload["vendor"]), case=expected_case, topology=str(payload["topology"]),
        identity=identity, expression=expression, vertex_count=int(payload["vertex_count"]),
        source_sha256=digest.lower(),
    )


def load_export(path: Path, *, expected_case: str) -> CanonicalIdentityArtifact:
    return normalize_export(json.loads(path.read_text()), expected_case=expected_case)


def qualification_status(exports: Mapping[str, CanonicalIdentityArtifact]) -> dict[str, Any]:
    missing = sorted(set(FROZEN_CASES) - set(exports))
    repeated = {}
    for left, right in (("case01", "case05"), ("case02", "case06")):
        if left in exports and right in exports:
            repeated[f"{left}/{right}"] = exports[left].identity_hash == exports[right].identity_hash
    return {
        "complete": not missing,
        "missing_cases": missing,
        "repeated_identity_stable": repeated,
        "ready_for_geometry_benchmark": not missing and all(repeated.values()),
    }

