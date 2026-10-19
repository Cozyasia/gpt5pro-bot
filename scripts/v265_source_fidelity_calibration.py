"""Deterministic OFFLINE calibration; writes scalars/hashes only, never images.

Public fixtures are split by identity (not by transformed image). No generated
positive or pose-adaptation acceptance is inferred from these benign transforms.
"""

from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from neyrobot_prod import selfie_v253_yunet_source_pixels as detector
from neyrobot_prod import selfie_v263_dense_identity_lock as dense
from neyrobot_prod import v265_source_fidelity as fidelity


def landmarks(image, models, left=False):
    frame = image[:, : int(image.shape[1] * 0.55)] if left else image
    box, _ = detector._yunet_face(frame, models / "yunet.onnx", label="offline")
    return dense._dense_landmarks_68(
        image, box, models / "pipnet.onnx", label="offline"
    )


def measure(source, candidate, sp, cp):
    return {
        **fidelity.morphology(sp, cp),
        **fidelity.appearance(source, candidate, sp, cp),
    }


def benign(image, angle, scale, gain):
    h, w = image.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    out = cv2.warpAffine(image, m, (w, h), borderMode=cv2.BORDER_REFLECT_101)
    return np.clip(out.astype(np.float32) * gain, 0, 255).astype(np.uint8)


def drift(image, points, region, strength=0.20):
    # Public-only controlled smooth inverse deformation, with known affected region.
    ids = {
        "mouth": range(48, 68),
        "nose": range(27, 36),
        "jaw_chin": range(4, 13),
        "lower_face": list(range(4, 13)) + list(range(48, 68)),
        "eyes": range(36, 48),
    }[region]
    p = points[list(ids)]
    center = p.mean(0)
    inter = np.linalg.norm(points[36:42].mean(0) - points[42:48].mean(0))
    h, w = image.shape[:2]
    y, x = np.mgrid[:h, :w].astype(np.float32)
    sx = max(np.ptp(p[:, 0]), inter * 0.35)
    sy = max(np.ptp(p[:, 1]), inter * 0.20)
    support = np.exp(-(((x - center[0]) / sx) ** 2) - ((y - center[1]) / sy) ** 2)
    if region in ("lower_face", "jaw_chin"):
        mx = x
        my = y - strength * inter * support
    else:
        mx = x - strength * (x - center[0]) * support
        my = y
    return cv2.remap(
        image, mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LINEAR
    )


def run(args):
    cv2.setNumThreads(1)
    cv2.setRNGSeed(0)
    expected = {
        "pipnet.onnx": dense._PIPNET_SHA256,
        "mobileface.onnx": dense._MOBILEFACE_SHA256,
        "yunet.onnx": detector._YUNET_SHA256,
    }
    for name, digest in expected.items():
        if hashlib.sha256((args.models / name).read_bytes()).hexdigest() != digest:
            raise ValueError("model digest mismatch: " + name)
    train = {"verify_now_2024.jpg", "verify_curie.jpg", "verify_bohr_1935.jpg"}
    holdout = {
        "verify_einstein_1921.jpg",
        "pose_center.jpg",
        "pose_left.jpg",
        "pose_right.jpg",
    }
    report = {
        "model_sha256": expected,
        "opencv": cv2.__version__,
        "cases": [],
        "human_approved_generated_positives": 0,
        "production_ready": False,
    }
    images = {}
    rows = []
    for name in sorted(train | holdout):
        raw = (args.fixtures / name).read_bytes()
        im = cv2.imdecode(np.frombuffer(raw, np.uint8), 1)
        sp = landmarks(im, args.models)
        images[name] = (im, sp)
        for i, (angle, scale, gain) in enumerate(
            [
                (0, 1, 1),
                (-6, 0.9, 0.85),
                (6, 1.05, 1.1),
                (3, 0.95, 0.95),
                (-3, 1.02, 1.05),
            ]
        ):
            candidate = benign(im, angle, scale, gain)
            try:
                m = measure(im, candidate, sp, landmarks(candidate, args.models))
                case = {
                    "source": name,
                    "source_sha256": hashlib.sha256(raw).hexdigest(),
                    "category": "benign",
                    "split": "train" if name in train else "holdout",
                    "variant": i,
                    "metrics": m,
                }
                if name in train:
                    rows.append(m)
            except (RuntimeError, ValueError) as e:
                case = {
                    "source": name,
                    "category": "benign",
                    "split": "train" if name in train else "holdout",
                    "variant": i,
                    "error": str(e),
                }
            report["cases"].append(case)
    limits = fidelity.measured_limits(rows)
    report["limits"] = limits
    for name, (im, sp) in images.items():
        for region in ["mouth", "nose", "jaw_chin", "lower_face", "eyes", "combined"]:
            altered = im.copy()
            for r in (
                ["mouth", "nose", "lower_face", "eyes"]
                if region == "combined"
                else [region]
            ):
                altered = drift(altered, sp, r)
            try:
                m = measure(im, altered, sp, landmarks(altered, args.models))
                case = {"metrics": m}
            except (ValueError, RuntimeError) as e:
                case = {"error": str(e)}
            report["cases"].append(
                {
                    "source": name,
                    "category": "controlled_drift",
                    "variant": region,
                    **case,
                }
            )
    # Cross-person source pairs, not recognition same-person calibration.
    for a, b in [
        ("verify_now_2024.jpg", "verify_curie.jpg"),
        ("pose_center.jpg", "verify_einstein_1921.jpg"),
    ]:
        ai, ap = images[a]
        bi, bp = images[b]
        try:
            case = {"metrics": measure(ai, bi, ap, bp)}
        except (ValueError, RuntimeError) as e:
            case = {"error": str(e)}
        report["cases"].append(
            {"source": a, "candidate": b, "category": "cross_person", **case}
        )
    if args.private_source and args.private_final:
        a = cv2.imread(str(args.private_source))
        b = cv2.imread(str(args.private_final))
        ap = landmarks(a, args.models)
        bp = landmarks(b, args.models, True)
        metrics = measure(a, b, ap, bp)
        ae = dense._mobileface_embedding(a, ap, args.models / "mobileface.onnx")
        be = dense._mobileface_embedding(b, bp, args.models / "mobileface.onnx")
        report["cases"].append(
            {
                "category": "human_rejected_generated",
                "metrics": metrics,
                "recognition_cosine": float(ae @ be),
                "source_sha256": hashlib.sha256(
                    args.private_source.read_bytes()
                ).hexdigest(),
                "candidate_sha256": hashlib.sha256(
                    args.private_final.read_bytes()
                ).hexdigest(),
            }
        )
    for case in report["cases"]:
        if "metrics" in case:
            case["exceeded"] = fidelity.compare_limits(case["metrics"], limits)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True))
    for category in [
        "benign",
        "controlled_drift",
        "cross_person",
        "human_rejected_generated",
    ]:
        cases = [c for c in report["cases"] if c["category"] == category]
        print(
            category,
            "total",
            len(cases),
            "exceeded",
            sum(bool(c.get("exceeded")) for c in cases),
            "unmeasurable",
            sum("error" in c for c in cases),
        )
    print(
        "PRODUCTION_READY=false; no human-approved generated positives; yaw/pitch not calibrated"
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--fixtures", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--private-source", type=Path)
    p.add_argument("--private-final", type=Path)
    run(p.parse_args())
