import json
from pathlib import Path
import unittest

from neyrobot_prod.v265_asset_policy import (
    REQUIRED_GRANTS,
    assert_production_eligible,
    load_asset_manifest,
    production_blockers,
)


MANIFEST = Path(__file__).parent / "fixtures" / "v265_l2_assets.json"


class L2AssetPolicyTests(unittest.TestCase):
    def test_current_faceverse_pack_is_fail_closed(self):
        manifest = load_asset_manifest(MANIFEST)
        self.assertFalse(manifest["production_integration_allowed"])
        self.assertEqual(len(production_blockers(manifest)), 6)
        with self.assertRaisesRegex(PermissionError, "research-only"):
            assert_production_eligible(manifest)

    def test_every_asset_records_all_required_grants(self):
        manifest = json.loads(MANIFEST.read_text())
        for asset in manifest["assets"].values():
            self.assertLessEqual(set(REQUIRED_GRANTS), set(asset["grants"]))
            self.assertFalse(asset["training_data_commercial_clearance"])


if __name__ == "__main__":
    unittest.main()
