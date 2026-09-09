import json
from pathlib import Path

import pytest

from neyrobot_prod.v265_asset_policy import (
    REQUIRED_GRANTS,
    assert_production_eligible,
    load_asset_manifest,
    production_blockers,
)


MANIFEST = Path(__file__).parent / "fixtures" / "v265_l2_assets.json"


def test_current_faceverse_pack_is_fail_closed():
    manifest = load_asset_manifest(MANIFEST)
    assert manifest["production_integration_allowed"] is False
    assert len(production_blockers(manifest)) == 6
    with pytest.raises(PermissionError, match="research-only"):
        assert_production_eligible(manifest)


def test_every_asset_records_all_required_grants():
    manifest = json.loads(MANIFEST.read_text())
    for asset in manifest["assets"].values():
        assert set(REQUIRED_GRANTS) <= set(asset["grants"])
        assert asset["training_data_commercial_clearance"] is False

