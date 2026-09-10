"""Fail-closed pilot validation; no network, pickle, or automatic rights approval."""

import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

CLASSES = [
    "background",
    "skin",
    "brows",
    "eyes",
    "eyelids",
    "upper_lip",
    "lower_lip",
    "mouth_interior",
    "teeth",
    "hair",
    "neck",
    "glasses_frame",
    "transparent_lens",
    "opaque_lens",
    "occlusion",
]
REGIONS = ["jaw", "chin", "nose", "mouth", "eyes", "cheeks", "brows"]
RIGHTS = [
    "commercial_ml_training",
    "derivative_weights",
    "commercial_server_inference",
    "perpetual_trained_weights",
    "worldwide",
    "no_inference_royalty",
    "provenance_warranty",
]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def array_hash(a):
    a = np.ascontiguousarray(a)
    return hashlib.sha256(
        str(a.shape).encode() + a.dtype.str.encode() + a.tobytes()
    ).hexdigest()


def asset(root, ref):
    p = (root / ref["path"]).resolve()
    require(p.is_relative_to(root) and p.is_file(), "asset outside root or missing")
    require(p.stat().st_size <= 512 * 1024**2, "asset exceeds pilot file limit")
    require(sha(p) == ref["sha256"], "asset SHA-256 mismatch")
    return p


def finite(a, shape=None):
    a = np.asarray(a)
    require(
        np.issubdtype(a.dtype, np.number) and np.isfinite(a).all(),
        "nonfinite/non-numeric array",
    )
    if shape is not None:
        require(a.shape == shape, "array shape mismatch")
    return a


def mesh(z):
    v = finite(z["vertices"])
    t = z["triangles"]
    require(
        v.ndim == 2 and v.shape[1] == 3 and len(v) >= 468,
        "native vertices must include >=468",
    )
    require(
        t.ndim == 2 and t.shape[1] == 3 and len(t) > 0 and t.dtype.kind in "iu",
        "triangles invalid",
    )
    require(t.min() >= 0 and t.max() < len(v), "triangle index out of range")
    require(len(np.unique(np.sort(t, axis=1), axis=0)) == len(t), "duplicate triangles")
    area = np.linalg.norm(
        np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]]), axis=1
    )
    require((area > 1e-12).all(), "degenerate triangles")
    edges = np.sort(np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]), axis=1)
    require(
        np.unique(edges, axis=0, return_counts=True)[1].max() <= 2, "non-manifold edge"
    )
    require(0.01 < np.ptp(v, axis=0).max() < 1.0, "non-metric face extent")
    return v, t


def validate(
    root, manifest="manifest.jsonl", ledger="rights.json", *, smoke=False, pilot=False
):
    root = Path(root).resolve()
    manifest_path = (root / manifest).resolve()
    require(manifest_path.is_relative_to(root), "manifest outside root")
    ledger_path = (root / ledger).resolve()
    require(ledger_path.is_relative_to(root), "ledger outside root")
    rights = json.loads(ledger_path.read_text())
    require(
        rights["manifest_sha256"] == sha(manifest_path),
        "rights ledger not bound to manifest",
    )
    agreements = rights["agreements"]
    rows = [json.loads(s) for s in manifest_path.read_text().splitlines() if s.strip()]
    require(bool(rows), "empty dataset")
    records, identities, topology = set(), {}, None
    for r in rows:
        require(r["schema_version"] == 1, "unsupported schema")
        require(r["record_id"] not in records, "duplicate record ID")
        records.add(r["record_id"])
        require(r["split"] in ["train", "validation", "test"], "unknown split")
        for k in [
            "identity_id",
            "parent_identity_id",
            "topology_version",
            "pose_id",
            "expression_id",
            "lighting_id",
        ]:
            require(
                isinstance(r[k], str) and bool(r[k].strip()), "empty identity/version"
            )
        agreement = agreements[r["rights_agreement_id"]]
        if smoke:
            require(
                agreement["status"] == "original_procedural_smoke_only",
                "smoke rights required",
            )
        else:
            require(
                agreement["status"] == "executed"
                and agreement["review_status"] == "approved",
                "unapproved rights",
            )
            require(
                bool(agreement["reviewer"]) and bool(agreement["licensor"]),
                "missing rights reviewer/licensor",
            )
            asset(root, agreement["document"])
            require(
                all(agreement["grants"].get(x) is True for x in RIGHTS),
                "rights grant missing",
            )
            require(
                not agreement["unresolved_restrictions"],
                "unresolved rights restriction",
            )
        paths = {
            k: asset(root, r[k])
            for k in [
                "neutral_mesh",
                "expression_mesh",
                "rgb",
                "labels",
                "camera",
                "correspondence",
            ]
        }
        with np.load(paths["neutral_mesh"], allow_pickle=False) as z:
            v, t = mesh(z)
            basis = finite(z["expression_basis"])
            require(
                basis.ndim == 3 and basis.shape[1:] == v.shape and len(basis) > 0,
                "expression basis shape",
            )
            regions = z["regions"]
            require(
                regions.shape == (len(v),) and regions.dtype.kind in "iu",
                "region labels shape",
            )
            require(
                set(range(len(REGIONS))).issubset(set(regions.tolist())),
                "missing critical geometry region",
            )
        require(
            array_hash(t.astype("<i4")) == r["topology_sha256"],
            "topology hash mismatch",
        )
        signature = (r["topology_version"], r["topology_sha256"], len(v), len(t))
        if topology is None:
            topology = signature
        require(signature == topology, "mixed/unmapped topology")
        with np.load(paths["correspondence"], allow_pickle=False) as z:
            ids, w = z["triangle_ids"], finite(z["barycentric"], (468, 3))
            require(
                ids.shape == (468,)
                and ids.dtype.kind in "iu"
                and ids.min() >= 0
                and ids.max() < len(t),
                "correspondence indices",
            )
            require(
                (w >= 0).all() and np.allclose(w.sum(1), 1, atol=1e-6),
                "correspondence weights",
            )
        with np.load(paths["expression_mesh"], allow_pickle=False) as z:
            ev, et = mesh(z)
            displacement = finite(z["displacement"], v.shape)
            require(
                np.array_equal(t, et) and np.allclose(ev, v + displacement, atol=1e-6),
                "expression/neutral mismatch",
            )
        rgb = np.load(paths["rgb"], allow_pickle=False)
        require(
            rgb.ndim == 3 and rgb.shape[2] == 3 and rgb.dtype == np.uint8,
            "RGB must be uint8 HWC NPY",
        )
        h, w = rgb.shape[:2]
        with np.load(paths["labels"], allow_pickle=False) as z:
            depth = finite(z["depth"], (h, w))
            normal = finite(z["normals"], (h, w, 3))
            sem, vis = z["semantic"], z["visibility"]
            require(
                sem.shape == (h, w)
                and sem.dtype.kind in "iu"
                and sem.min() >= 0
                and sem.max() < len(CLASSES),
                "semantic labels",
            )
            require(
                vis.shape == (h, w) and vis.dtype == np.bool_ and vis.any(),
                "visibility mask",
            )
            require(
                (depth[vis] > 0).all()
                and np.allclose(np.linalg.norm(normal[vis], axis=1), 1, atol=0.01),
                "depth/normals invalid",
            )
            coeff = finite(z["expression"], (len(basis),))
            require(
                np.allclose(
                    np.einsum("e,enc->nc", coeff, basis), displacement, atol=1e-5
                ),
                "expression displacement inconsistent",
            )
            finite(z["landmarks"], (468, 3))
            require(
                z["landmark_visibility"].shape == (468,)
                and z["landmark_visibility"].dtype == np.bool_,
                "landmark visibility",
            )
            require(
                z["triangle_visibility"].shape == (len(t),)
                and z["triangle_visibility"].dtype == np.bool_,
                "triangle visibility",
            )
        c = json.loads(paths["camera"].read_text())
        require(
            c["units"] == "m"
            and c["handedness"] == "right"
            and c["convention"] == "world_to_camera_x_right_y_down_z_forward",
            "camera convention",
        )
        k, rot, trans = (
            finite(c["K"], (3, 3)),
            finite(c["R"], (3, 3)),
            finite(c["t"], (3,)),
        )
        require(
            np.allclose(rot.T @ rot, np.eye(3), atol=1e-5)
            and np.isclose(np.linalg.det(rot), 1, atol=1e-5),
            "improper camera R",
        )
        require(
            k[0, 0] > 0 and k[1, 1] > 0 and np.allclose(k[2], [0, 0, 1]), "invalid K"
        )
        require(
            np.allclose(finite(r["pose"]["R"], (3, 3)), rot)
            and np.allclose(finite(r["pose"]["t"], (3,)), trans),
            "pose/camera mismatch",
        )
        require(
            r["semantic_classes"] == CLASSES and r["units"] == "m",
            "label/metric convention mismatch",
        )
        ident = (
            r["parent_identity_id"],
            r["split"],
            r["neutral_mesh"]["sha256"],
            array_hash(v),
            v,
        )
        old = identities.get(r["identity_id"])
        require(
            old is None or old[:4] == ident[:4],
            "identity neutral/lineage/split changed",
        )
        identities[r["identity_id"]] = ident
    # Resolve every lineage to a known root and reject cycles and split changes.
    for name, val in identities.items():
        seen, at = set(), name
        while True:
            require(
                at in identities and at not in seen, "missing parent or lineage cycle"
            )
            seen.add(at)
            parent, split, *_ = identities[at]
            require(split == val[1], "parent/descendant split leakage")
            if parent == at:
                break
            at = parent
    # Geometry-derived near-duplicates: rigid Procrustes, metric scale retained.
    # Conservative screen, not a guarantee against all perceptual duplicates.
    entries = list(identities.items())
    for i, (name, a) in enumerate(entries):
        for other, b in entries[:i]:
            if a[1] == b[1]:
                continue
            require(a[2] != b[2] and a[3] != b[3], "duplicate mesh across splits")
            va, vb = a[4] - a[4].mean(0), b[4] - b[4].mean(0)
            u, _, vt = np.linalg.svd(va.T @ vb)
            align = u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt
            rms = np.sqrt(np.mean(np.sum((va @ align - vb) ** 2, axis=1)))
            require(
                rms > 0.0001, "near-duplicate canonical source across splits (<=0.1mm)"
            )
    image_splits = {}
    for r in rows:
        h = r["rgb"]["sha256"]
        require(
            h not in image_splits or image_splits[h] == r["split"],
            "duplicate RGB source across splits",
        )
        image_splits[h] = r["split"]
    if pilot:
        require(
            len(rows) == 19200 and len(identities) == 100,
            "pilot requires 100 identities / 19200 renders",
        )
        require(
            {r["split"] for r in rows} == {"train", "validation", "test"},
            "pilot requires all three splits",
        )
        for identity in identities:
            samples = [r for r in rows if r["identity_id"] == identity]
            combinations = {
                (r["pose_id"], r["expression_id"], r["lighting_id"]) for r in samples
            }
            require(
                len(samples) == len(combinations) == 192,
                "pilot duplicate/missing render combinations",
            )
            require(
                tuple(
                    len({r[k] for r in samples})
                    for k in ["pose_id", "expression_id", "lighting_id"]
                )
                == (12, 8, 2),
                "pilot factorial mismatch",
            )
    return {
        "records": len(rows),
        "identities": len(identities),
        "topology": topology,
        "commercial_training_allowed": not smoke,
        "manifest_sha256": sha(manifest_path),
        "rights_sha256": sha(ledger_path),
        "near_duplicate_screen": "rigid-aligned metric RMS >0.1mm; not perceptual proof",
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("root")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--pilot", action="store_true")
    a = p.parse_args()
    print(json.dumps(validate(a.root, smoke=a.smoke, pilot=a.pilot), indent=2))
