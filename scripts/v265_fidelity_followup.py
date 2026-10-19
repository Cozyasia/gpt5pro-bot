"""Replay original mixed benign holdout and optional private failure; scalars only."""

import argparse, json
from pathlib import Path
import cv2
from scripts.v265_source_fidelity_calibration import landmarks, benign
from scripts.v265_nuisance_calibration import transforms
from neyrobot_prod import v265_source_fidelity as f
from neyrobot_prod import v265_eye_fidelity_lab as eye


def measure(a, b, ap, bp):
    return {
        "morphology": f.morphology(ap, bp),
        "appearance": eye.compare(
            eye.descriptors(a, ap, include_face=True),
            eye.descriptors(b, bp, include_face=True),
        ),
    }


def evaluate(m, limits):
    return {
        "morphology_exceeded": f.compare_limits(m["morphology"], limits["morphology"]),
        "appearance_exceeded": f.compare_limits(m["appearance"], limits["eye"]),
    }


def run(a):
    cv2.setNumThreads(1)
    report = {"legacy_holdout_replay": [], "production_ready": False}
    limits = json.loads(a.calibration.read_text())["source_limits"]
    for name in [
        "verify_einstein_1921.jpg",
        "pose_center.jpg",
        "pose_left.jpg",
        "pose_right.jpg",
    ]:
        im = cv2.imread(str(a.fixtures / name))
        p = landmarks(im, a.models)
        for i, (angle, scale, gain) in enumerate(
            [
                (0, 1, 1),
                (-6, 0.9, 0.85),
                (6, 1.05, 1.1),
                (3, 0.95, 0.95),
                (-3, 1.02, 1.05),
            ]
        ):
            out = benign(im, angle, scale, gain)
            try:
                m = measure(im, out, p, landmarks(out, a.models))
                r = {**m, **evaluate(m, limits[name])}
            except (ValueError, RuntimeError) as ex:
                r = {"error": str(ex)}
            report["legacy_holdout_replay"].append({"source": name, "variant": i, **r})
    if a.private_source and a.private_final:
        im = cv2.imread(str(a.private_source))
        p = landmarks(im, a.models)
        rows = []
        for category, variant, out in transforms(im):
            m = measure(im, out, p, landmarks(out, a.models))
            rows.append(m)
        lim = {
            "morphology": f.measured_limits([r["morphology"] for r in rows]),
            "eye": f.measured_limits([r["appearance"] for r in rows]),
        }
        out = cv2.imread(str(a.private_final))
        m = measure(im, out, p, landmarks(out, a.models, True))
        report["human_rejected_generated"] = {
            **m,
            **evaluate(m, lim),
            "limits_fitted_only_on_benign_source": lim,
            "old_production_recognition": 0.778736,
            "old_geometry_pass": True,
        }
    a.output.write_text(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--fixtures", type=Path, required=True)
    p.add_argument("--calibration", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--private-source", type=Path)
    p.add_argument("--private-final", type=Path)
    run(p.parse_args())
