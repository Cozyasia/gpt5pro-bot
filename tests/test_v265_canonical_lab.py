"""Factorization and invalid mesh contracts, not visual acceptance."""

import hashlib
import json
from pathlib import Path
import unittest
import numpy as np
from neyrobot_prod.v265_canonical_lab import (
    CanonicalModel,
    Parameters,
    identity_digest,
    mesh_validity,
    require_renderable,
)


class CanonicalTests(unittest.TestCase):
    def test_source_expression_and_target_identity_cannot_enter_retarget(self):
        rng = np.random.default_rng(265)
        m = CanonicalModel(
            rng.normal(size=(68, 3)),
            rng.normal(size=(68, 3, 40)),
            rng.normal(size=(68, 3, 10)),
            [[0, 1, 2]],
            np.arange(68),
        )
        source = Parameters.from62(rng.normal(size=62))
        target = Parameters.from62(rng.normal(size=62))
        expected = m.retarget(source, target)
        changed_source = Parameters(
            source.camera + 7, source.identity, source.expression + 10
        )
        changed_target = Parameters(
            target.camera - 8, target.identity - 20, target.expression
        )
        np.testing.assert_array_equal(
            expected, m.retarget(changed_source, changed_target)
        )
        self.assertEqual(identity_digest(m, source), identity_digest(m, changed_source))
        self.assertFalse(
            np.array_equal(
                expected,
                m.retarget(
                    source,
                    Parameters(target.camera, target.identity, target.expression + 1),
                ),
            )
        )

    def test_inversion_collapse_and_extreme_scale_never_reach_renderer(self):
        a = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)
        for b in (a[[0, 2, 1]], a * 0, a * 20):
            r = mesh_validity(
                a,
                b,
                [[0, 1, 2]],
                min_scale=0.1,
                max_scale=10,
                max_displacement=100,
                max_edge_delta=100,
            )
            self.assertFalse(r["passes_engineering_bounds"])
            with self.assertRaisesRegex(ValueError, "invalid_geometry"):
                require_renderable(
                    r,
                    accessory_mask_verified=True,
                    visibility_verified=True,
                    mouth_texture_compatible=True,
                )

    def test_valid_geometry_does_not_override_missing_semantic_evidence(self):
        a = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)
        r = mesh_validity(
            a,
            a,
            [[0, 1, 2]],
            min_scale=0.1,
            max_scale=10,
            max_displacement=1,
            max_edge_delta=1,
        )
        self.assertTrue(r["passes_engineering_bounds"])
        with self.assertRaisesRegex(ValueError, "accessory_ownership_unverified"):
            require_renderable(
                r,
                accessory_mask_verified=False,
                visibility_verified=True,
                mouth_texture_compatible=True,
            )
        with self.assertRaisesRegex(
            ValueError, "mouth_texture_expression_incompatible"
        ):
            require_renderable(
                r,
                accessory_mask_verified=True,
                visibility_verified=True,
                mouth_texture_compatible=False,
            )


class NegativeFixtureTests(unittest.TestCase):
    def test_exact_frozen_binary_integrity_and_repeated_sources(self):
        p = Path("tests/fixtures/v265_matrix")
        manifest = json.loads((p / "manifest.json").read_text())
        for case in (
            "case01",
            "case02",
            "case04",
            "case05",
            "case06",
            "case07",
            "case08",
        ):
            for suffix in ("_source.jpg", "_stage1.png"):
                f = p / (case + suffix)
                self.assertEqual(
                    hashlib.sha256(f.read_bytes()).hexdigest(),
                    manifest["files"][f.name]["sha256"],
                    f.name,
                )
        self.assertEqual(
            (p / "case01_source.jpg").read_bytes(),
            (p / "case05_source.jpg").read_bytes(),
        )
        self.assertEqual(
            (p / "case02_source.jpg").read_bytes(),
            (p / "case06_source.jpg").read_bytes(),
        )
