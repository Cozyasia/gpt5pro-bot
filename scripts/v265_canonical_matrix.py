"""L decomposition audit on frozen public cases. No production runtime import.

Produces measurements, not an accepted render. Parameter equality by construction
is reported separately from independently observed 2D landmark agreement.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import time
import cv2
import numpy as np
from neyrobot_prod.v265_canonical_lab import (
    CanonicalModel,
    Parameters,
    project,
    identity_digest,
    mesh_validity,
)
from neyrobot_prod.v265_source_fidelity import morphology


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def roi_from_box(box):
    x, y, w, h = map(float, box[:4])
    old = (w + h) / 2
    size = int(old * 1.58)
    cx, cy = x + w / 2, y + h / 2 + old * 0.14
    return np.array(
        [cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2], np.float32
    )


def crop(image, roi):
    sx, sy, ex, ey = np.rint(roi).astype(int)
    out = np.zeros((ey - sy, ex - sx, 3), np.uint8)
    h, w = image.shape[:2]
    x0, y0, x1, y1 = max(sx, 0), max(sy, 0), min(ex, w), min(ey, h)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("empty face crop")
    out[y0 - sy : y1 - sy, x0 - sx : x1 - sx] = image[y0:y1, x0:x1]
    return cv2.resize(out, (120, 120), interpolation=cv2.INTER_LINEAR)


def infer(image, detector, session, mean, std, left=False):
    im = image[:, : round(image.shape[1] * 0.55)] if left else image
    # YuNet at bounded resolution, return detector box in native coordinates.
    factor = min(1.0, 1000 / max(im.shape[:2]))
    small = cv2.resize(im, None, fx=factor, fy=factor) if factor != 1 else im
    detector.setInputSize((small.shape[1], small.shape[0]))
    _, faces = detector.detect(small)
    if faces is None:
        raise ValueError("no face")
    face = max(faces, key=lambda f: f[2] * f[3]).copy()
    face[:14] /= factor
    roi = roi_from_box(face)
    x = ((crop(image, roi).astype(np.float32) - 127.5) / 128).transpose(2, 0, 1)[None]
    session.setInput(x)
    p = session.forward().reshape(-1) * std + mean
    return Parameters.from62(p), roi


def run(a):
    cv2.setNumThreads(1)
    pid = os.getpid()
    baseline = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    model = CanonicalModel.load(a.assets / "canonical.npz")
    with np.load(a.assets / "canonical.npz", allow_pickle=False) as z:
        mean, std = z["param_mean"], z["param_std"]
    session = cv2.dnn.readNetFromONNX(str(a.assets / "regressor.onnx"))
    detector = cv2.FaceDetectorYN_create(
        str(a.models / "yunet.onnx"), "", (320, 320), 0.7
    )
    warmed = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    from scripts.v265_transfer_matrix import pointset

    cache = {}
    observed_cache = {}
    rows = []
    a.output.mkdir(parents=True, exist_ok=True)
    for case in ["case01", "case02", "case04", "case05", "case06", "case07", "case08"]:
        started = time.monotonic()
        sp = a.fixtures / (case + "_source.jpg")
        tp = a.fixtures / (case + "_stage1.png")
        key = digest(sp)
        # Exact same source is inferred once; target data cannot affect identity.
        if key not in cache:
            cache[key] = infer(cv2.imread(str(sp)), detector, session, mean, std)
            observed_cache[key] = pointset(cv2.imread(str(sp)), a.models)[2]
        source, sroi = cache[key]
        target_image = cv2.resize(
            cv2.imread(str(tp)), (1856, 2304), interpolation=cv2.INTER_LANCZOS4
        )
        target, troi = infer(target_image, detector, session, mean, std, True)
        observed_target = pointset(target_image, a.models, True)[2]
        canonical = model.retarget(source, target)
        final = project(canonical, target.camera, troi)
        target_mesh = project(
            model.shape(target.identity, target.expression), target.camera, troi
        )
        # Canonical 3D orientation is also audited separately from projection.
        iod = np.linalg.norm(
            target_mesh[model.landmarks[36:42], :2].mean(0)
            - target_mesh[model.landmarks[42:48], :2].mean(0)
        )
        validity = mesh_validity(
            target_mesh,
            final,
            model.triangles,
            min_scale=0.1,
            max_scale=10.0,
            max_displacement=iod,
            max_edge_delta=iod,
        )
        sf = project(
            model.shape(source.identity, source.expression), source.camera, sroi
        )
        row = {
            "case": case,
            "source_sha256": key,
            "stage1_raw_sha256": digest(tp),
            "normalized_stage1_sha256": hashlib.sha256(
                cv2.imencode(".png", target_image, [cv2.IMWRITE_PNG_COMPRESSION, 2])[
                    1
                ].tobytes()
            ).hexdigest(),
            "source_identity_digest": identity_digest(model, source),
            "source_identity_parameters": source.identity.tolist(),
            "source_expression_parameters": source.expression.tolist(),
            "target_expression_parameters": target.expression.tolist(),
            "target_camera": target.camera.tolist(),
            "coefficient_identity_retention_linf": 0.0,
            "coefficient_target_expression_retention_linf": 0.0,
            "coefficient_metrics_are_algebraic_not_visual_proof": True,
            "mesh_validity": validity,
            "model_source_to_final_2d_morphology_NOT_independent": morphology(
                sf[model.landmarks, :2], final[model.landmarks, :2]
            ),
            "pipnet_source_to_model_fit_error": morphology(
                observed_cache[key], sf[model.landmarks, :2]
            ),
            "pipnet_target_to_model_fit_error": morphology(
                observed_target, target_mesh[model.landmarks, :2]
            ),
            "pipnet_source_to_projected_L_geometry_error_NOT_render": morphology(
                observed_cache[key], final[model.landmarks, :2]
            ),
            "accessory_ownership_verified": False,
            "mouth_texture_expression_compatible": False,
            "render_prequalified": False,
            "image_produced": False,
            "elapsed_s": time.monotonic() - started,
            "source_model_landmarks": sf[model.landmarks, :2].tolist(),
            "target_model_landmarks": target_mesh[model.landmarks, :2].tolist(),
            "final_model_landmarks": final[model.landmarks, :2].tolist(),
        }
        rows.append(row)
        (a.output / (case + "_L.json")).write_text(json.dumps(row, indent=2))
        print(
            case,
            "projected inversions",
            validity["projected_inversions"],
            "3D reversals",
            validity["orientation_3d_reversals"],
            flush=True,
        )
    summary = {
        "rows": rows,
        "unique_sources": len(cache),
        "pid_stable": os.getpid() == pid,
        "baseline_rss_highwater_kib": baseline,
        "loaded_rss_highwater_kib": warmed,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "model_array_bytes": model.resident_array_bytes,
        "regressor_bytes": (a.assets / "regressor.onnx").stat().st_size,
        "assets_sha256": {p.name: digest(p) for p in a.assets.glob("*") if p.is_file()},
        "production_memory_qualified": False,
        "daemon_baseline_included": False,
        "notes": [
            "3DDFA V2 affine camera; no calibrated perspective camera",
            "Separate learned coefficient spaces do not prove disentangled inference",
            "No synthetic 2D residual appended to model identity",
            "Mesh inversions must be resolved before any compositor",
            "Accessory segmentation and mouth appearance synthesis unresolved",
        ],
    }
    (a.output / "summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--assets", type=Path, required=True)
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--fixtures", type=Path, default=Path("tests/fixtures/v265_matrix"))
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args())
