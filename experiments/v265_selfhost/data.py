"""Rights-gated real-record loader and automatic train-only basis preparation."""

import json
from pathlib import Path
import numpy as np
from experiments.v265_prior.ingest import validate, asset, sha, array_hash, require


def admitted(root, smoke):
    root = Path(root).resolve()
    audit = validate(root, smoke=smoke)
    rows = [
        json.loads(x)
        for x in (root / "manifest.jsonl").read_text().splitlines()
        if x.strip()
    ]
    # Extended target assets are checksum-bound by the same manifest/rights ledger.
    stable = {}
    expression_hash = None
    for r in rows:
        for key in ["albedo", "uv", "ownership"]:
            asset(root, r[key])
        rgb = np.load(asset(root, r["rgb"]), allow_pickle=False)
        with np.load(asset(root, r["neutral_mesh"]), allow_pickle=False) as z:
            count = len(z["vertices"])
            h = array_hash(z["expression_basis"])
        if expression_hash is None:
            expression_hash = h
        require(
            h == expression_hash,
            "v1 requires a shared canonical expression basis; supplier conversion required",
        )
        uv = np.load(asset(root, r["uv"]), allow_pickle=False)
        albedo = np.load(asset(root, r["albedo"]), allow_pickle=False)
        require(
            uv.shape == (count, 2)
            and np.isfinite(uv).all()
            and uv.min() >= 0
            and uv.max() <= 1,
            "invalid canonical UV",
        )
        require(
            albedo.ndim == 3
            and albedo.shape[2] == 3
            and np.isfinite(albedo).all()
            and albedo.min() >= 0
            and albedo.max() <= 1,
            "invalid native linear RGB UV map",
        )
        with np.load(asset(root, r["ownership"]), allow_pickle=False) as z:
            for key in ["support", "protected", "neck", "occlusion"]:
                require(
                    z[key].shape == rgb.shape[:2] and z[key].dtype == np.bool_,
                    "ownership target invalid",
                )
        invariant = (r["albedo"]["sha256"], r["uv"]["sha256"])
        require(
            r["identity_id"] not in stable or stable[r["identity_id"]] == invariant,
            "identity albedo/UV changed across scene",
        )
        stable[r["identity_id"]] = invariant
    return root, rows, audit


def prepare(root, output, smoke=False, identity_dim=192, residual_dim=32):
    root, rows, audit = admitted(root, smoke)
    unique = {r["identity_id"]: r for r in rows if r["split"] == "train"}
    require(len(unique) >= 2, "need at least two TRAIN identities for basis")
    geometry = []
    reference = None
    for r in unique.values():
        with np.load(asset(root, r["neutral_mesh"]), allow_pickle=False) as z:
            geometry.append(z["vertices"])
            reference = {k: z[k].copy() for k in z.files}
    g = np.asarray(geometry, dtype=np.float32)
    mean = g.mean(0)
    n = len(mean)
    e = reference["expression_basis"].reshape(len(reference["expression_basis"]), -1).T
    u, s, _ = np.linalg.svd(e, full_matrices=False)
    q = u[:, s > max(s.max() * 1e-6, 1e-12)]
    data = (g - mean).reshape(len(g), -1)
    data -= data @ q @ q.T
    _, s, v = np.linalg.svd(data, full_matrices=False)
    identity = np.zeros((identity_dim, n * 3), np.float32)
    rank = min(identity_dim, int((s > 1e-7).sum()))
    identity[:rank] = v[:rank] * np.maximum(s[:rank, None], 1e-5)
    # Original topology-smoothed residual basis, not external identity weights.
    rng = np.random.default_rng(265)
    res = rng.normal(size=(residual_dim, n, 3)).astype("float32")
    triangles = reference["triangles"].astype("int64")
    edges = np.unique(
        np.sort(
            np.concatenate(
                [triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]]
            ),
            axis=1,
        ),
        axis=0,
    )
    for _ in range(8):
        acc = np.zeros_like(res)
        count = np.zeros(n, np.float32)
        for a, b in [(edges[:, 0], edges[:, 1]), (edges[:, 1], edges[:, 0])]:
            for k in range(residual_dim):
                np.add.at(acc[k], a, res[k, b])
            np.add.at(count, a, 1)
        res = 0.5 * res + 0.5 * acc / np.maximum(count[None, :, None], 1)
    # Restrict expressive regions; orthogonalize AFTER spatial weighting.
    sensitive = np.isin(reference["regions"], [3, 4, 5, 6])
    res[:, sensitive] *= 0.2
    flat = res.reshape(residual_dim, -1)
    flat -= flat @ q @ q.T
    res = flat.reshape(residual_dim, n, 3)
    res *= 0.0015 / max(
        np.linalg.norm(res, axis=2).sum(0).max(), 1e-8
    )  # bound for all codes in [-1,1]
    r = next(iter(unique.values()))
    with np.load(asset(root, r["correspondence"]), allow_pickle=False) as z:
        ids = z["triangle_ids"]
        w = z["barycentric"]
    np.savez(
        output,
        neutral=mean,
        identity_basis=identity.reshape(identity_dim, n, 3),
        residual_basis=res,
        expression_basis=reference["expression_basis"],
        triangles=triangles,
        regions=reference["regions"],
        correspondence_ids=ids.astype("int64"),
        correspondence_weights=w.astype("float32"),
        uv=np.load(asset(root, r["uv"]), allow_pickle=False),
    )
    meta = {
        "basis_train_identity_ids": sorted(unique),
        "effective_identity_rank": rank,
        "native_vertices": n,
        "model_asset_sha256": sha(output),
        **audit,
        "basis_version": "train-PCA-topology-residual-v1",
    }
    Path(str(output) + ".json").write_text(json.dumps(meta, indent=2))
    return meta


def albedo_target(native, size=16):
    # Preserve native source asset; deterministic low-res supervision view for v1 head.
    from PIL import Image

    return np.stack(
        [
            np.asarray(
                Image.fromarray(native[:, :, c].astype("float32"), mode="F").resize(
                    (size, size), Image.Resampling.BILINEAR
                )
            )
            for c in range(3)
        ]
    )


class Records:
    def __init__(self, root, split, basis, smoke=False):
        self.root, allrows, self.admission = admitted(root, smoke)
        self.rows = [r for r in allrows if r["split"] == split]
        require(bool(self.rows), "empty " + split)
        self.groups = {}
        for i, r in enumerate(self.rows):
            self.groups.setdefault(r["identity_id"], []).append(i)
        self.model = np.load(basis, allow_pickle=False)
        self.matrix = (
            np.concatenate([self.model["identity_basis"], self.model["residual_basis"]])
            .reshape(224, -1)
            .T
        )
        self.inverse = np.linalg.pinv(self.matrix, rcond=1e-5)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        peers = [
            j
            for j in self.groups[r["identity_id"]]
            if self.rows[j]["pose_id"] != r["pose_id"]
        ]
        require(bool(peers), "independent pose pair required")
        b = self.rows[peers[0]]
        load = lambda row, key: np.load(asset(self.root, row[key]), allow_pickle=False)
        camera = json.loads(asset(self.root, r["camera"]).read_text())
        with load(r, "neutral_mesh") as z:
            neutral = z["vertices"].copy()
        with load(r, "labels") as z:
            labels = {k: z[k].copy() for k in z.files}
        with load(r, "ownership") as z:
            ownership = {k: z[k].copy() for k in z.files}
        coefficients = (
            self.inverse @ (neutral - self.model["neutral"]).ravel()
        ).astype("float32")
        return dict(
            rgb=load(r, "rgb").transpose(2, 0, 1).astype("float32") / 255,
            paired_rgb=load(b, "rgb").transpose(2, 0, 1).astype("float32") / 255,
            neutral=neutral,
            coefficients=coefficients[:192],
            residual_coefficients=coefficients[192:],
            K=np.asarray(camera["K"], np.float32),
            R=np.asarray(camera["R"], np.float32),
            t=np.asarray(camera["t"], np.float32),
            albedo=albedo_target(load(r, "albedo")),
            **labels,
            **ownership,
            identity_id=r["identity_id"],
            record_id=r["record_id"]
        )
