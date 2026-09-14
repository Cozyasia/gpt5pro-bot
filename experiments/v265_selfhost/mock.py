"""Original procedural dataset: TEST ONLY, never identity-quality evidence."""

import argparse, json
from pathlib import Path
import numpy as np
from experiments.v265_prior.ingest import sha, array_hash, CLASSES
from .geometry import raster, project_np


def generate(root, identities=6, size=32):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    u, v = np.meshgrid(np.linspace(0, 1, 26), np.linspace(0, 1, 20))
    uv = np.stack([u.ravel(), v.ravel()], 1).astype("float32")
    x = (u - 0.5) * 0.16 * (0.4 + 0.6 * np.sin(np.pi * v))
    y = (v - 0.5) * 0.22
    z = -0.02 * np.exp(-((u - 0.5) ** 2 + (v - 0.45) ** 2) / 0.04)
    neutral = np.stack([x.ravel(), y.ravel(), z.ravel()], 1).astype("float32")
    n = len(neutral)
    tri = []
    for row in range(19):
        for col in range(25):
            j = row * 26 + col
            tri.extend([[j, j + 1, j + 26], [j + 1, j + 27, j + 26]])
    t = np.array(tri, np.int32)
    np.save(root / "uv.npy", uv)
    regions = np.clip((v.ravel() * 7).astype(int), 0, 6).astype("int32")
    # Four original nonhuman-control modes; no claim of real blendshape semantics.
    basis = np.zeros((4, n, 3), np.float32)
    mouth = np.exp(-((uv[:, 0] - 0.5) ** 2 / 0.06 + (uv[:, 1] - 0.7) ** 2 / 0.02))
    basis[0, :, 1] = mouth * (uv[:, 1] - 0.7) * 0.02
    basis[1, :, 1] = mouth * (np.abs(uv[:, 0] - 0.5) - 0.12) * 0.01
    basis[2, :, 2] = mouth * 0.003
    basis[3, :, 1] = (
        0.001 * np.sin(uv[:, 0] * np.pi) * np.exp(-((uv[:, 1] - 0.3) ** 2) / 0.01)
    )
    corr_ids = np.arange(468, dtype="int32")
    corr_w = np.tile([1.0, 0.0, 0.0], (468, 1)).astype("float32")
    np.savez(root / "correspondence.npz", triangle_ids=corr_ids, barycentric=corr_w)
    rows = []
    rng = np.random.default_rng(265)
    for identity in range(identities):
        folder = root / f"id{identity:03d}"
        folder.mkdir()
        split = (
            "train"
            if identity < identities // 2
            else ("validation" if identity < identities - 1 else "test")
        )
        face = neutral.copy()
        face[:, 0] *= 0.8 + 0.07 * identity
        face[:, 2] *= 0.85 + 0.06 * identity
        np.savez(
            folder / "neutral.npz",
            vertices=face,
            triangles=t,
            expression_basis=basis,
            regions=regions,
        )
        base_color = rng.uniform(0.25, 0.75, 3)
        ay, ax = np.mgrid[:16, :16]
        albedo = np.clip(
            base_color
            + 0.035 * np.sin(ax[..., None] * 0.9 + identity)
            + 0.015 * np.cos(ay[..., None]),
            0,
            1,
        ).astype("float32")
        np.save(folder / "albedo.npy", albedo)
        for pose, angle in enumerate([-0.25, 0.2]):
            R = np.array(
                [
                    [np.cos(angle), 0, np.sin(angle)],
                    [0, 1, 0],
                    [-np.sin(angle), 0, np.cos(angle)],
                ],
                np.float32,
            )
            K = np.array(
                [[size * 2.7, 0, size / 2], [0, size * 2.7, size / 2], [0, 0, 1]],
                np.float32,
            )
            trans = np.array([0, 0, 0.65], np.float32)
            for expression in range(2):
                coeff = np.array([expression, 0.6 * expression, 0, 0], np.float32)
                disp = np.einsum("e,enc->nc", coeff, basis)
                expressed = face + disp
                for lighting in range(2):
                    tag = f"p{pose}e{expression}l{lighting}"
                    p = folder / tag
                    p.mkdir()
                    rendered = raster(
                        expressed,
                        t,
                        K,
                        R,
                        trans,
                        size,
                        uv,
                        albedo,
                        np.ones(n, np.uint8),
                        illumination=(0.8 + 0.2 * lighting, 0.1 * lighting, 0),
                    )
                    rgb = np.rint(rendered["rgb"] * 255).astype("uint8")
                    np.save(p / "rgb.npy", rgb)
                    np.savez(
                        p / "expression.npz",
                        vertices=expressed,
                        triangles=t,
                        displacement=disp,
                    )
                    xy, zz = project_np(expressed, K, R, trans)
                    landmarks = np.concatenate(
                        [xy[t[corr_ids, 0]], zz[t[corr_ids, 0], None]], 1
                    ).astype("float32")
                    tri_vis = np.zeros(len(t), bool)
                    tri_vis[
                        np.unique(rendered["triangle_id"][rendered["visibility"]])
                    ] = True
                    np.savez(
                        p / "labels.npz",
                        depth=rendered["depth"],
                        normals=rendered["normals"],
                        semantic=rendered["semantic"],
                        visibility=rendered["visibility"],
                        expression=coeff,
                        landmarks=landmarks,
                        landmark_visibility=np.ones(468, bool),
                        triangle_visibility=tri_vis,
                    )
                    protected = np.zeros((size, size), bool)
                    protected[:, size * 3 // 4 :] = True
                    neck = np.zeros_like(protected)
                    neck[-3:] = True
                    np.savez(
                        p / "ownership.npz",
                        support=rendered["visibility"],
                        protected=protected,
                        neck=neck,
                        occlusion=np.zeros_like(neck),
                    )
                    camera = dict(
                        K=K.tolist(),
                        R=R.tolist(),
                        t=trans.tolist(),
                        units="m",
                        handedness="right",
                        convention="world_to_camera_x_right_y_down_z_forward",
                    )
                    (p / "camera.json").write_text(json.dumps(camera))
                    files = dict(
                        neutral_mesh=folder / "neutral.npz",
                        expression_mesh=p / "expression.npz",
                        rgb=p / "rgb.npy",
                        labels=p / "labels.npz",
                        camera=p / "camera.json",
                        correspondence=root / "correspondence.npz",
                        uv=root / "uv.npy",
                        albedo=folder / "albedo.npy",
                        ownership=p / "ownership.npz",
                    )
                    record = dict(
                        schema_version=1,
                        record_id=f"id{identity}-{tag}",
                        identity_id=f"id{identity}",
                        parent_identity_id=f"id{identity}",
                        split=split,
                        pose_id=str(pose),
                        expression_id=str(expression),
                        lighting_id=str(lighting),
                        topology_version="ORIGINAL-MOCK-DENSE520-NOT-HUMAN",
                        topology_sha256=array_hash(t.astype("<i4")),
                        units="m",
                        semantic_classes=CLASSES,
                        pose={"R": R.tolist(), "t": trans.tolist()},
                        rights_agreement_id="TEST_ONLY",
                    )
                    record.update(
                        {
                            key: {
                                "path": str(path.relative_to(root)),
                                "sha256": sha(path),
                            }
                            for key, path in files.items()
                        }
                    )
                    rows.append(record)
    (root / "manifest.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (root / "rights.json").write_text(
        json.dumps(
            {
                "manifest_sha256": sha(root / "manifest.jsonl"),
                "commercial_training_allowed": False,
                "agreements": {
                    "TEST_ONLY": {
                        "status": "original_procedural_smoke_only",
                        "notice": "TEST ONLY / NO COMMERCIAL TRAINING",
                    }
                },
            },
            indent=2,
        )
    )
    return {
        "records": len(rows),
        "identities": identities,
        "commercial_training_allowed": False,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("root")
    p.add_argument("--identities", type=int, default=6)
    p.add_argument("--size", type=int, default=32)
    a = p.parse_args()
    print(generate(a.root, a.identities, a.size))
