"""Independent nuisance interventions on sealed identities; no target RGB to encoder."""

import json, hashlib
from pathlib import Path
import numpy as np
import torch
from experiments.v265_quality.factory import anatomy, expression, camera, texture
from experiments.v265_quality.train import Model
from experiments.v265_selfhost.geometry import raster, project_np


def measure(root, run):
    root, run = Path(root), Path(run)
    report = json.loads((run / "report.json").read_text())
    s = dict(np.load(root / "topology.npz"))
    model = Model(
        s,
        report["backbone"],
        report["latent"],
        report["representation"],
        report["uv_size"],
    )
    model.load_state_dict(torch.load(run / "weights.pt", weights_only=True))
    model.eval()
    torch.set_num_threads(2)
    rows = [json.loads(l) for l in (root / "manifest.jsonl").read_text().splitlines()]
    selected = [r for r in rows if r["split"] == "test" and r["view"] == 0]
    modes = ["neutral", "smile", "open", "asymmetric", "yaw", "light", "glasses"]
    values = {mode: [] for mode in modes}
    albedos = {mode: [] for mode in modes}
    mouth = {mode: [] for mode in modes}
    cross = []
    silhouette = []
    keys = [
        (-0.3, 0.4),
        (0.3, 0.4),
        (0, 0.36),
        (0, 0.46),
        (0, 0.26),
        (0, 0.18),
        (0, 0.84),
    ]
    ids = [np.argmin(np.sum((s["uv"] * 2 - 1 - p) ** 2, axis=1)) for p in keys]

    def mouth_parameters(v):
        a, b, up, low, phil, nose, chin = v[ids]
        return np.array(
            [
                np.linalg.norm(a - b),
                np.linalg.norm(up - low),
                np.linalg.norm(up - phil),
                np.linalg.norm(up - nose),
                np.linalg.norm(low - chin),
            ]
        )

    for row in selected:
        with np.load(root / row["path"]) as rec:
            n = rec["neutral"]
            coeff = rec["coefficients"]
            residual = rec["residual"]
        predictions = []
        canonical_albedo = []
        for mode in modes:
            e = np.zeros(8)
            e[0] = 1 if mode == "smile" else 0
            e[1] = 1 if mode == "open" else 0
            e[4] = 1 if mode == "asymmetric" else 0
            K, R, t = camera(45 if mode == "yaw" else 0, 0)
            tex, lab = texture(
                1000 + row["identity"], accessory=2 if mode == "glasses" else 0
            )
            v = expression(s, n, e)
            light = (0.65, 0.2, -0.1) if mode == "light" else (1, 0, 0)
            rendered = raster(
                v, s["triangles"], K, R, t, 64, s["uv"], tex, illumination=light
            )
            rgb = torch.tensor(rendered["rgb"]).permute(2, 0, 1)[None]
            with torch.no_grad():
                p, c, a, _ = model(rgb)
            predictions.append(p[0].numpy())
            canonical_albedo.append(a[0].numpy())
        base = predictions[0]
        for mode, p, a in zip(modes, predictions, canonical_albedo):
            values[mode].append(
                float(np.sqrt(np.mean(np.sum((p - base) ** 2, axis=1))) * 1000)
            )
            albedos[mode].append(float(np.mean((a - canonical_albedo[0]) ** 2)))
            mouth[mode].append(
                (abs(mouth_parameters(p) - mouth_parameters(n)) * 1000).tolist()
            )
        # Infer A (broad smile) once; use independent neutral B pose. No B image encoding.
        immutable = predictions[1].copy()
        digest = hashlib.sha256(immutable.tobytes()).hexdigest()
        K, R, t = camera(-40, 15)
        px, _ = project_np(immutable, K, R, t)
        gx, _ = project_np(n, K, R, t)
        cross.append(float(np.sqrt(np.mean(np.sum((px - gx) ** 2, axis=1)))))
        pr = raster(immutable, s["triangles"], K, R, t, 64)["visibility"]
        gt = raster(n, s["triangles"], K, R, t, 64)["visibility"]
        silhouette.append(float((pr & gt).sum() / max((pr | gt).sum(), 1)))
        assert digest == hashlib.sha256(immutable.tobytes()).hexdigest()
    result = dict(
        test_identities=len(selected),
        controlled_pairs=len(selected) * (len(modes) - 1),
        identity_drift_mm={m: float(np.mean(v)) for m, v in values.items()},
        albedo_drift_mse={m: float(np.mean(v)) for m, v in albedos.items()},
        mouth_metric_names=[
            "width",
            "lip_separation_not_thickness_ratio",
            "philtrum_relation",
            "mouth_nose",
            "mouth_chin",
        ],
        mouth_errors_mm={m: np.mean(v, axis=0).tolist() for m, v in mouth.items()},
        withheld_B_projection_rmse_px=float(np.mean(cross)),
        withheld_B_silhouette_iou=float(np.mean(silhouette)),
        case08_pass=False,
        case07_pass=False,
        reason="Intrinsic lip thickness/teeth/cavity topology and physical accessories are absent; numerical patch metrics are insufficient for acceptance.",
    )
    (run / "controlled.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    import sys

    measure(sys.argv[1], sys.argv[2])
