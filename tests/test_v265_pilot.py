"""Adversarial admission tests on original procedural surfaces, never quality data."""

import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from experiments.v265_prior.ingest import validate, sha, array_hash, CLASSES
from experiments.v265_prior.evaluate import evaluate_pair, topology_metrics


def fixture(root):
    x, y = np.meshgrid(np.linspace(-0.06, 0.06, 26), np.linspace(-0.08, 0.08, 20))
    v = np.stack(
        [x.ravel(), y.ravel(), (0.01 * (x * x + y * y)).ravel()], axis=1
    ).astype("float32")
    tri = []
    for row in range(19):
        for col in range(25):
            i = row * 26 + col
            tri.extend([[i, i + 1, i + 26], [i + 1, i + 27, i + 26]])
    t = np.array(tri, dtype="int32")
    basis = np.zeros((2, len(v), 3), dtype="float32")
    basis[0, :, 2] = 0.001
    np.savez(
        root / "neutral.npz",
        vertices=v,
        triangles=t,
        expression_basis=basis,
        regions=np.arange(len(v)) % 7,
    )
    np.savez(
        root / "expression.npz", vertices=v, triangles=t, displacement=np.zeros_like(v)
    )
    np.save(root / "rgb.npy", np.zeros((16, 16, 3), dtype="uint8"))
    np.savez(
        root / "correspondence.npz",
        triangle_ids=np.arange(468) % len(t),
        barycentric=np.tile([1.0, 0, 0], (468, 1)),
    )
    normal = np.zeros((16, 16, 3))
    normal[:, :, 2] = 1
    np.savez(
        root / "labels.npz",
        depth=np.ones((16, 16)),
        normals=normal,
        semantic=np.ones((16, 16), dtype="uint8"),
        visibility=np.ones((16, 16), dtype=bool),
        expression=np.zeros(2),
        landmarks=np.zeros((468, 3)),
        landmark_visibility=np.ones(468, dtype=bool),
        triangle_visibility=np.ones(len(t), dtype=bool),
    )
    camera = dict(
        K=[[500, 0, 8], [0, 500, 8], [0, 0, 1]],
        R=np.eye(3).tolist(),
        t=[0, 0, 1],
        units="m",
        handedness="right",
        convention="world_to_camera_x_right_y_down_z_forward",
    )
    (root / "camera.json").write_text(json.dumps(camera))
    r = dict(
        schema_version=1,
        record_id="a",
        identity_id="id1",
        parent_identity_id="id1",
        split="train",
        pose_id="frontal",
        expression_id="neutral",
        lighting_id="studio",
        topology_version="original-grid-v1",
        topology_sha256=array_hash(t.astype("<i4")),
        units="m",
        pose={k: camera[k] for k in ["R", "t"]},
        semantic_classes=CLASSES,
        rights_agreement_id="smoke",
    )
    for key, file in dict(
        neutral_mesh="neutral.npz",
        expression_mesh="expression.npz",
        rgb="rgb.npy",
        labels="labels.npz",
        camera="camera.json",
        correspondence="correspondence.npz",
    ).items():
        r[key] = {"path": file, "sha256": sha(root / file)}
    rows = [r, {**r, "record_id": "b"}]
    write(root, rows)
    return rows, v, t, basis


def write(root, rows):
    (root / "manifest.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (root / "rights.json").write_text(
        json.dumps(
            {
                "manifest_sha256": sha(root / "manifest.jsonl"),
                "agreements": {"smoke": {"status": "original_procedural_smoke_only"}},
            }
        )
    )


class Admission(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rows, self.v, self.t, self.basis = fixture(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def bad(self, pattern):
        write(self.root, self.rows)
        with self.assertRaisesRegex((ValueError, KeyError), pattern):
            validate(self.root, smoke=True)

    def test_valid_smoke_not_commercial(self):
        self.assertFalse(validate(self.root, smoke=True)["commercial_training_allowed"])
        with self.assertRaisesRegex(ValueError, "unapproved rights"):
            validate(self.root)

    def test_pilot_cannot_be_satisfied_by_smoke(self):
        with self.assertRaisesRegex(ValueError, "100 identities"):
            validate(self.root, smoke=True, pilot=True)

    def test_checksum(self):
        (self.root / "rgb.npy").write_bytes(b"tamper")
        self.bad("SHA-256")

    def test_missing_rights(self):
        (self.root / "rights.json").unlink()
        with self.assertRaises(FileNotFoundError):
            validate(self.root)

    def test_ledger_binding(self):
        (self.root / "manifest.jsonl").write_text("{}")
        with self.assertRaisesRegex(ValueError, "bound"):
            validate(self.root)

    def test_escape(self):
        self.rows[0]["rgb"]["path"] = "../outside.npy"
        self.bad("outside root")

    def test_parent_leakage(self):
        self.rows[1].update(identity_id="child", parent_identity_id="id1", split="test")
        self.bad("descendant")

    def test_duplicate_mesh(self):
        self.rows[1].update(identity_id="id2", parent_identity_id="id2", split="test")
        self.bad("duplicate mesh")

    def test_cycle(self):
        for r in self.rows:
            r["parent_identity_id"] = "missing"
        self.bad("missing parent")

    def test_bad_camera(self):
        c = json.loads((self.root / "camera.json").read_text())
        c["R"][0][0] = -1
        (self.root / "camera.json").write_text(json.dumps(c))
        for r in self.rows:
            r["camera"]["sha256"] = sha(self.root / "camera.json")
        self.bad("improper camera")

    def test_topology_hash(self):
        self.rows[0]["topology_sha256"] = "0" * 64
        self.bad("topology hash")

    def test_expression_baked_in(self):
        np.savez(
            self.root / "expression.npz",
            vertices=self.v + 0.001,
            triangles=self.t,
            displacement=np.zeros_like(self.v),
        )
        for r in self.rows:
            r["expression_mesh"]["sha256"] = sha(self.root / "expression.npz")
        self.bad("expression/neutral")

    def test_near_duplicate_different_bytes(self):
        v = self.v.copy()
        v[:, 2] += 1e-5
        np.savez(
            self.root / "neutral2.npz",
            vertices=v,
            triangles=self.t,
            expression_basis=self.basis,
            regions=np.arange(len(v)) % 7,
        )
        np.savez(
            self.root / "expression2.npz",
            vertices=v,
            triangles=self.t,
            displacement=np.zeros_like(v),
        )
        r = self.rows[1]
        r.update(identity_id="id2", parent_identity_id="id2", split="test")
        for key, f in [
            ("neutral_mesh", "neutral2.npz"),
            ("expression_mesh", "expression2.npz"),
        ]:
            r[key] = {"path": f, "sha256": sha(self.root / f)}
        self.bad("near-duplicate")

    def test_identity_invariance(self):
        r = self.rows[1].copy()
        r["neutral_mesh"] = dict(r["neutral_mesh"])
        np.savez(
            self.root / "other.npz",
            vertices=self.v * 1.01,
            triangles=self.t,
            expression_basis=self.basis,
            regions=np.arange(len(self.v)) % 7,
        )
        r["neutral_mesh"] = {
            "path": "other.npz",
            "sha256": sha(self.root / "other.npz"),
        }
        self.rows[1] = r
        self.bad("expression/neutral|identity neutral")

    def test_dataset_pair(self):
        from experiments.v265_prior.train import PilotDataset

        d = PilotDataset(self.root, "train", smoke=True)
        self.assertEqual(d[0]["rgb"].shape, (3, 16, 16))

    def test_cross_view_encoder_never_receives_target(self):
        from experiments.v265_prior.evaluate import cross_view_protocol

        names = [
            "left_corner",
            "right_corner",
            "upper_outer",
            "upper_inner",
            "lower_outer",
            "lower_inner",
            "nose_base",
            "nose_left",
            "nose_right",
            "chin",
        ]
        ids = dict(zip(names, [100, 110, 130, 156, 208, 182, 260, 270, 280, 300]))
        calls = []

        def infer(image):
            calls.append(image.copy())
            return self.v

        inputs = dict(
            neutral_gt=self.v,
            expression_basis=self.basis,
            target_expression=np.zeros(2),
            withheld_b=self.v,
            k=np.eye(3),
            r=np.eye(3),
            t=np.array([0, 0, 1]),
            triangles=self.t,
            regions={"mouth": np.arange(100, 200)},
            visible=np.ones(len(self.v), bool),
            boundary=np.arange(26),
            mouth_ids=ids,
        )
        pair = dict(
            pair_id="a-b",
            split="test",
            source_identity_id="a",
            target_identity_id="a",
            source_image_sha256="a" * 64,
            target_image_sha256="b" * 64,
            evaluation_inputs=inputs,
        )
        result = cross_view_protocol(infer, np.zeros((2, 2, 3)), [pair, pair])
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            result["pairs"][0]["source_canonical_hash"],
            result["pairs"][1]["source_canonical_hash"],
        )
        pair["target_identity_id"] = "other"
        with self.assertRaisesRegex(ValueError, "same identity"):
            cross_view_protocol(infer, np.zeros((2, 2, 3)), [pair])

    def test_foldover_detection(self):
        v = self.v.copy()
        v[:, 0] *= -1
        self.assertEqual(
            topology_metrics(v, self.v, self.t)["orientation_failures"], len(self.t)
        )

    def test_evaluation_no_uncalibrated_pass(self):
        names = [
            "left_corner",
            "right_corner",
            "upper_outer",
            "upper_inner",
            "lower_outer",
            "lower_inner",
            "nose_base",
            "nose_left",
            "nose_right",
            "chin",
        ]
        ids = dict(zip(names, [100, 110, 130, 156, 208, 182, 260, 270, 280, 300]))
        r = evaluate_pair(
            self.v,
            self.v,
            self.basis,
            np.zeros(2),
            self.v,
            np.eye(3),
            np.eye(3),
            np.array([0, 0, 1]),
            self.t,
            {"mouth": np.arange(100, 200)},
            np.ones(len(self.v), bool),
            np.arange(26),
            ids,
        )
        self.assertFalse(r["machine_prequalified"])
        self.assertEqual(r["case08"], "UNQUALIFIED")
        self.assertEqual(r["geometry"]["orientation_failures"], 0)


if __name__ == "__main__":
    unittest.main()
