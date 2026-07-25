# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from neyrobot_prod import selfie_storage_v205 as v205


class SelfieStorageV205Tests(unittest.TestCase):
    def test_storage_root_is_always_data(self):
        with mock.patch.object(v205, "_ensure_root", return_value=Path("/data/celebrity_selfie")):
            self.assertEqual(str(v205.storage_root(None)), "/data/celebrity_selfie")

    def test_vlad_a4_slot_is_prepared(self):
        meta = v205.CHARACTER_ADDITIONS["vlad_a4_bumaga"]
        self.assertEqual(meta["name"], "Влад А4 (Бумага)")
        self.assertEqual(meta["required_refs"], 3)

    def test_source_tree_environment_is_overwritten(self):
        package = types.ModuleType("neyrobot_prod")
        base = types.ModuleType("neyrobot_prod.celebrity_selfie")
        base.CHARACTERS = {}
        base._storage_root = lambda _mod: Path("/opt/render/project/src/celebrity_selfie")

        old_package = sys.modules.get("neyrobot_prod")
        old_base = sys.modules.get("neyrobot_prod.celebrity_selfie")
        sys.modules["neyrobot_prod"] = package
        sys.modules["neyrobot_prod.celebrity_selfie"] = base
        saved = os.environ.get("CELEBRITY_SELFIE_DATA_DIR")
        os.environ["CELEBRITY_SELFIE_DATA_DIR"] = "/opt/render/project/src/celebrity_selfie"
        try:
            with mock.patch.object(v205, "_ensure_root", return_value=Path("/data/celebrity_selfie")):
                with mock.patch.object(Path, "mkdir"):
                    self.assertTrue(v205.patch())
                    self.assertEqual(str(base._storage_root(None)), "/data/celebrity_selfie")
            self.assertEqual(os.environ["CELEBRITY_SELFIE_DATA_DIR"], "/data/celebrity_selfie")
            self.assertIn("vlad_a4_bumaga", base.CHARACTERS)
        finally:
            if saved is None:
                os.environ.pop("CELEBRITY_SELFIE_DATA_DIR", None)
            else:
                os.environ["CELEBRITY_SELFIE_DATA_DIR"] = saved
            if old_package is not None:
                sys.modules["neyrobot_prod"] = old_package
            else:
                sys.modules.pop("neyrobot_prod", None)
            if old_base is not None:
                sys.modules["neyrobot_prod.celebrity_selfie"] = old_base
            else:
                sys.modules.pop("neyrobot_prod.celebrity_selfie", None)


if __name__ == "__main__":
    unittest.main()
