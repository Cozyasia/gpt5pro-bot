"""Fail-closed asset policy for experimental V265/L2 model artifacts."""

from __future__ import annotations

import json
from pathlib import Path


REQUIRED_GRANTS = (
    "commercial_use",
    "server_side_inference",
    "asset_redistribution",
    "unattended_ci_use",
)


def load_asset_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def production_blockers(manifest: dict) -> list[str]:
    blockers: list[str] = []
    for name, asset in manifest["assets"].items():
        grants = asset.get("grants", {})
        missing = [grant for grant in REQUIRED_GRANTS if grants.get(grant) is not True]
        if missing:
            blockers.append(f"{name}: missing explicit grants: {', '.join(missing)}")
        if asset.get("training_data_commercial_clearance") is not True:
            blockers.append(f"{name}: training/data-derived clearance is not explicit")
    return blockers


def assert_production_eligible(manifest: dict) -> None:
    blockers = production_blockers(manifest)
    if blockers:
        raise PermissionError("V265 L2 assets are research-only:\n" + "\n".join(blockers))

