"""Measure control-point error of production Gaussian average vs offline TPS."""

import argparse, json
from pathlib import Path
import numpy as np
import cv2
from scripts.v265_transfer_matrix import pointset
from neyrobot_prod import dense68_engine_v265 as e
from neyrobot_prod.v265_shape_lab import tps_inverse_roi
from neyrobot_prod.v265_transfer_lab import full_face_support


def run(a):
    cv2.setNumThreads(1)
    results = []
    for case in ("case01", "case02", "case04"):
        source = cv2.imread(str(a.fixtures / (case + "_source.jpg")))
        target = cv2.imread(str(a.output / case / "stage1.png"))
        sb, s5, sd = pointset(source, a.models)
        tb, t5, td = pointset(target, a.models, True)
        matrix, _ = e.v263._similarity_transform(s5, t5)
        projected = e._project_points(matrix, sd)
        minimum = min(tb[2:4])
        desired = e.v263._desired_identity_geometry(
            projected, td, minimum, strict=False
        )
        sigma = max(
            e.v263._DENSE_SIGMA_MIN,
            min(e.v263._DENSE_SIGMA_MAX, float(minimum) * e.v263._DENSE_SIGMA_FRACTION),
        )
        offsets = (desired[:, None, :] - desired[None, :, :]) / sigma
        weights = np.exp(-0.5 * (offsets**2).sum(2))
        ws = weights.sum(1)
        inverse = desired - (weights @ (desired - projected)) / np.maximum(
            ws[:, None], 1e-6
        ) * np.clip(ws[:, None], 0, 1)
        errors = np.linalg.norm(inverse - projected, axis=1)
        mask = full_face_support(target.shape, td, round(target.shape[1] * 0.55))
        box = e._mask_box(mask, pad=60, firewall_x=round(target.shape[1] * 0.55))
        x0, y0, x1, y1 = box
        _, tps_error, _ = tps_inverse_roi(
            np.zeros((y1 - y0, x1 - x0, 3), np.uint8), projected, desired, box, minimum
        )
        results.append(
            {
                "case": case,
                "gaussian_control_mean_px": float(errors.mean()),
                "gaussian_control_max_px": float(errors.max()),
                "gaussian_jaw_mean_px": float(errors[:17].mean()),
                "gaussian_chin_mean_px": float(errors[7:10].mean()),
                "tps_control_max_px": tps_error,
            }
        )
    a.report.write_text(
        json.dumps({"cases": results, "production_accepted": False}, indent=2)
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--fixtures", type=Path, default=Path("tests/fixtures/v265_matrix"))
    p.add_argument("--report", type=Path, required=True)
    run(p.parse_args())
