"""Source-specific nuisance envelopes and three eye descriptor ablations.

Calibration uses exact-source transforms only, before evaluating any drift.
Held-out transformations are disjoint. Synthetic perspective is NOT real 3D pose
and expression is unlabelled; no generated acceptance or runtime wiring.
"""

import argparse, json, hashlib
from pathlib import Path
import cv2
import numpy as np
from scripts.v265_source_fidelity_calibration import landmarks, drift, benign
from neyrobot_prod import v265_source_fidelity as f
from neyrobot_prod import v265_eye_fidelity_lab as eye


def transforms(im, heldout=False):
    values = (0.87, 1.13) if heldout else (0.75, 0.95, 1.05, 1.25)
    for v in values:
        yield "brightness", str(v), np.clip(im.astype(float) * v, 0, 255).astype(
            "uint8"
        )
        yield "contrast", str(v), np.clip(
            (im.astype(float) - 128) * v + 128, 0, 255
        ).astype("uint8")
        color = np.array([v, 1, 2 - v])
        yield "color", str(v), np.clip(im.astype(float) * color, 0, 255).astype("uint8")
    for q in ([83, 93] if heldout else [70, 80, 90, 98]):
        yield "jpeg", str(q), cv2.imdecode(
            cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, q])[1], 1
        )
    yield "png", "lossless", cv2.imdecode(cv2.imencode(".png", im)[1], 1)
    for scale in ([0.83, 1.07] if heldout else [0.7, 0.9, 1.1, 1.2]):
        yield "resize", str(scale), cv2.resize(
            im, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
        )
        yield "scale", str(scale), benign(im, 0, scale, 1)
    for a in ([-4, 4] if heldout else [-8, -6, 6, 8]):
        yield "roll", str(a), benign(im, a, 1, 1)
    # Deliberately excluded from fitting: report separately, no 3D-pose labels.
    if heldout:
        h, w = im.shape[:2]
        for v in [-0.025, 0.025]:
            src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
            dst = src + np.float32([[v * w, 0], [-v * w, v * h], [0, 0], [0, -v * h]])
            yield "perspective_proxy", str(v), cv2.warpPerspective(
                im,
                cv2.getPerspectiveTransform(src, dst),
                (w, h),
                borderMode=cv2.BORDER_REFLECT_101,
            )


def eye_stress(im, p, kind):
    h, w = im.shape[:2]
    y, x = np.mgrid[:h, :w].astype(np.float32)
    mx = x.copy()
    my = y.copy()
    iod = np.linalg.norm(p[42:48].mean(0) - p[36:42].mean(0))
    for ids in [range(36, 42), range(42, 48)]:
        pts = p[list(ids)]
        cx, cy = pts.mean(0)
        width = np.ptp(pts[:, 0])
        height = max(np.ptp(pts[:, 1]), iod * 0.025)
        support = np.exp(
            -(((x - cx) / (width * 0.7)) ** 4) - ((y - cy) / (height * 1.4)) ** 4
        )
        if kind == "aperture":
            my -= 0.4 * (y - cy) * support
        elif kind == "width":
            mx -= 0.25 * (x - cx) * support
        elif kind == "eyelid":
            my -= 0.10 * width * support * (y < cy)
        elif kind == "iris_relation_proxy":
            # No iris detector: central-eye translation, not anatomical iris truth.
            local = np.exp(
                -(((x - cx) / (width * 0.18)) ** 4) - ((y - cy) / (height * 0.65)) ** 4
            )
            mx -= width * 0.12 * local
    return cv2.remap(im, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)


def run(a):
    global landmarks
    if a.landmark_mode == "median_boxes":
        from neyrobot_prod.v265_landmark_measurement_lab import landmarks
    cv2.setNumThreads(1)
    cv2.setRNGSeed(0)
    names = [
        "verify_now_2024.jpg",
        "verify_curie.jpg",
        "verify_bohr_1935.jpg",
        "verify_einstein_1921.jpg",
        "pose_center.jpg",
        "pose_left.jpg",
        "pose_right.jpg",
    ]
    report = {
        "method": "per-source observed nuisance maxima; no tuned multiplier",
        "landmark_mode": a.landmark_mode,
        "cases": [],
        "source_limits": {},
        "production_ready": False,
        "human_approved_generated_positives": 0,
    }
    old = json.loads(
        Path("tests/fixtures/v265_source_fidelity_audit.json").read_text()
    )["limits"]

    def process(name, im, sp, ed, candidate, cat, variant, split):
        row = {"source": name, "category": cat, "variant": variant, "split": split}
        try:
            cp = landmarks(candidate, a.models)
            row["morphology"] = f.morphology(sp, cp)
            from neyrobot_prod.v265_shape_lab import configuration

            source_config, candidate_config = configuration(sp), configuration(cp)
            row["configuration_2d"] = {
                k: abs(float(candidate_config[k]) - float(source_config[k]))
                for k in source_config
                if k != "configuration_signed"
            }
            row["eye"] = eye.compare(
                ed,
                eye.descriptors(
                    candidate, cp, include_face=True, include_profiles=True
                ),
            )
            try:
                row["old_exceeded"] = f.compare_limits(
                    {**row["morphology"], **f.appearance(im, candidate, sp, cp)}, old
                )
            except ValueError as e:
                row["old_invalid"] = str(e)
        except (ValueError, RuntimeError) as e:
            row["error"] = str(e)
        return row

    for name in names:
        raw = (a.fixtures / name).read_bytes()
        im = cv2.imdecode(np.frombuffer(raw, np.uint8), 1)
        sp = landmarks(im, a.models)
        ed = eye.descriptors(im, sp, include_face=True, include_profiles=True)
        training = [
            process(name, im, sp, ed, v, c, n, "source_self_fit")
            for c, n, v in transforms(im)
        ]
        good = [r for r in training if "error" not in r]
        limits = {
            "morphology": f.measured_limits([r["morphology"] for r in good]),
            "eye": f.measured_limits([r["eye"] for r in good]),
            "configuration_2d": f.measured_limits(
                [r["configuration_2d"] for r in good]
            ),
            "source_sha256": hashlib.sha256(raw).hexdigest(),
        }
        report["source_limits"][name] = limits
        rows = training + [
            process(name, im, sp, ed, v, c, n, "heldout_transform")
            for c, n, v in transforms(im, True)
        ]
        for region in ["mouth", "nose", "jaw_chin", "lower_face", "combined"]:
            candidate = im.copy()
            for r in (
                ["mouth", "nose", "lower_face"] if region == "combined" else [region]
            ):
                candidate = drift(candidate, sp, r)
            rows.append(
                process(
                    name, im, sp, ed, candidate, "controlled_drift", region, "negative"
                )
            )
        for kind in ["aperture", "width", "eyelid", "iris_relation_proxy"]:
            rows.append(
                process(
                    name,
                    im,
                    sp,
                    ed,
                    eye_stress(im, sp, kind),
                    "eye_stress",
                    kind,
                    "negative",
                )
            )
        for row in rows:
            if "error" not in row:
                row["morphology_exceeded"] = f.compare_limits(
                    row["morphology"], limits["morphology"]
                )
                row["eye_exceeded"] = f.compare_limits(row["eye"], limits["eye"])
                row["configuration_exceeded"] = f.compare_limits(
                    row["configuration_2d"], limits["configuration_2d"]
                )
        report["cases"].extend(rows)
        print("CALIBRATED_SOURCE", name, flush=True)
    # Real pose/expression pairs remain unlabelled source-photo changes, never benign PASS truth.
    report["unsupported_domains"] = [
        "real yaw/pitch",
        "expression",
        "occlusion",
        "cast shadows",
        "human-approved generated positives",
    ]
    a.output.write_text(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--fixtures", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--landmark-mode", choices=["production", "median_boxes"], default="production"
    )
    run(p.parse_args())
