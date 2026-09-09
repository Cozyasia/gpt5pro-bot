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
from neyrobot_prod.v265_canonical_fit_lab import fit_source_diagnostic
from neyrobot_prod.v265_canonical_visibility import mesh_render_audit, visibility_audit
from neyrobot_prod.v265_canonical_correspondence import correspondence
from neyrobot_prod.v265_expression_contract import mouth_decomposition_report
from neyrobot_prod.v265_canonical_semantics import (
    REGIONS,
    accessory_edge_hypothesis,
    accessory_policy,
    completeness_report,
    semantic_region_map,
)
from neyrobot_prod.v265_canonical_texture import pixel_centres_to_mesh_boundaries


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
    fit_cache = {}
    rows = []
    a.output.mkdir(parents=True, exist_ok=True)
    for case in ["case01", "case02", "case04", "case05", "case06", "case07", "case08"]:
        started = time.monotonic()
        sp = a.fixtures / (case + "_source.jpg")
        tp = a.fixtures / (case + "_stage1.png")
        key = digest(sp)
        # Exact same source is inferred once; target data cannot affect identity.
        source_image = cv2.imread(str(sp))
        if key not in cache:
            cache[key] = infer(source_image, detector, session, mean, std)
            observed_cache[key] = pointset(source_image, a.models)[2]
        source, sroi = cache[key]
        if key not in fit_cache:
            fit_cache[key] = fit_source_diagnostic(
                model, source, sroi, observed_cache[key], std[12:]
            )
        fitted_source, fit_evidence = fit_cache[key]
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
        corr = correspondence(
            pixel_centres_to_mesh_boundaries(sf),
            pixel_centres_to_mesh_boundaries(final),
            model.triangles,
            troi,
        )
        corr_scalars = {
            k: v for k, v in corr.items() if k not in ("source_xy", "mesh_visible")
        }
        sample_shape = corr["mesh_visible"].shape
        sample_scale = 256 / float(max(troi[2:] - troi[:2]))
        sampled_landmarks = (
            final[model.landmarks, :2] - troi[:2]
        ) * sample_scale
        source_accessory = accessory_edge_hypothesis(
            source_image, sf[model.landmarks, :2]
        )
        target_accessory = accessory_edge_hypothesis(
            target_image, target_mesh[model.landmarks, :2]
        )
        yy, xx = np.indices(sample_shape)
        target_global = np.stack(
            (
                (xx + 0.5) / sample_scale + troi[0],
                (yy + 0.5) / sample_scale + troi[1],
            ),
            axis=2,
        )
        tx = np.clip(np.floor(target_global[:, :, 0]).astype(int), 0, target_image.shape[1] - 1)
        ty = np.clip(np.floor(target_global[:, :, 1]).astype(int), 0, target_image.shape[0] - 1)
        target_accessory_sample = target_accessory["mask"][ty, tx]
        face_sample = np.isfinite(corr["source_xy"]).all(axis=2)
        occluded_sample = face_sample & ~corr["mesh_visible"]
        regions = semantic_region_map(
            sample_shape,
            sampled_landmarks,
            face_sample,
            accessory=target_accessory_sample,
            occluded=occluded_sample,
        )
        source_xy = corr["source_xy"] - 0.5
        sx = np.clip(np.floor(np.nan_to_num(source_xy[:, :, 0], nan=0)).astype(int), 0, source_image.shape[1] - 1)
        sy = np.clip(np.floor(np.nan_to_num(source_xy[:, :, 1], nan=0)).astype(int), 0, source_image.shape[0] - 1)
        source_accessory_sample = source_accessory["mask"][sy, sx]
        mouth_interior = regions == REGIONS.index("mouth_interior")
        accessory_or_occlusion = np.isin(
            regions, [REGIONS.index("accessories"), REGIONS.index("occlusion")]
        )
        source_replaced = (
            corr["mesh_visible"]
            & ~source_accessory_sample
            & ~target_accessory_sample
            & ~mouth_interior
        )
        expression_owned = mouth_interior | accessory_or_occlusion
        ownership = completeness_report(regions, source_replaced, expression_owned)
        policy = accessory_policy(source_accessory["present"], target_accessory["present"])
        ownership["identity_complete"] = bool(
            ownership["identity_complete"]
            and policy["compatible"]
            and source_accessory["segmentation_verified"]
            and target_accessory["segmentation_verified"]
        )
        ownership["accessory_policy"] = policy
        ownership["source_accessory_evidence"] = {
            k: v for k, v in source_accessory.items() if k != "mask"
        }
        ownership["target_accessory_evidence"] = {
            k: v for k, v in target_accessory.items() if k != "mask"
        }
        ownership["critical_pixels_left_target_only"] = int(
            sum(ownership["critical_target_unresolved"].values())
        )
        del corr
        native_corr = None
        if case == "case06":
            native_roi = np.r_[
                np.maximum(0, np.floor(troi[:2])),
                np.minimum(
                    [target_image.shape[1], target_image.shape[0]], np.ceil(troi[2:])
                ),
            ]
            native_side = int(max(native_roi[2:] - native_roi[:2]))
            if native_side <= 1536:
                native = correspondence(
                    sf, final, model.triangles, native_roi, max_side=native_side
                )
                native_corr = {
                    k: v
                    for k, v in native.items()
                    if k not in ("source_xy", "mesh_visible")
                }
                native_corr["native_roi_side"] = native_side
                native_corr["global_integer_roi"] = native_roi.tolist()
                native_corr["target_pixel_step"] = 1
                del native
            else:
                native_corr = {
                    "unsupported_native_roi_side": native_side,
                    "render_prequalified": False,
                }
        row = {
            "case": case,
            "source_sha256": key,
            "stage1_raw_sha256": digest(tp),
            "normalized_stage1_sha256": hashlib.sha256(
                cv2.imencode(".png", target_image, [cv2.IMWRITE_PNG_COMPRESSION, 2])[
                    1
                ].tobytes()
            ).hexdigest(),
            "source_fit_diagnostic": fit_evidence,
            "fitted_source_identity_digest": identity_digest(model, fitted_source),
            "fitted_source_is_NOT_promoted": True,
            "source_identity_digest": identity_digest(model, source),
            "source_identity_parameters": source.identity.tolist(),
            "source_expression_parameters": source.expression.tolist(),
            "target_expression_parameters": target.expression.tolist(),
            "target_camera": target.camera.tolist(),
            "coefficient_identity_retention_linf": 0.0,
            "coefficient_target_expression_retention_linf": 0.0,
            "coefficient_metrics_are_algebraic_not_visual_proof": True,
            "mesh_validity": validity,
            "pointwise_correspondence": corr_scalars,
            "case06_native_correspondence": native_corr,
            "visibility_diagnostic": visibility_audit(
                sf, target_mesh, final, model.triangles, sroi, troi
            ),
            "triangle_mesh_render": mesh_render_audit(
                sf, target_mesh, final, model.triangles, troi
            ),
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
            "mouth_identity_expression_decomposition": mouth_decomposition_report(
                observed_cache[key], observed_target, final[model.landmarks, :2]
            ),
            "semantic_identity_completeness": ownership,
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
        "max_triangle_raster_bytes": max(
            r["triangle_mesh_render"]["raster_array_bytes"] for r in rows
        ),
        "semantic_critical_pixels_left_target_only": {
            r["case"]: r["semantic_identity_completeness"][
                "critical_pixels_left_target_only"
            ]
            for r in rows
        },
        "semantic_identity_complete": {
            r["case"]: r["semantic_identity_completeness"]["identity_complete"]
            for r in rows
        },
        "case06_full_render": bool(
            next(r for r in rows if r["case"] == "case06")["triangle_mesh_render"][
                "render_completed"
            ]
            and not next(r for r in rows if r["case"] == "case06")[
                "triangle_mesh_render"
            ]["foldover"]
            and next(r for r in rows if r["case"] == "case06")[
                "triangle_mesh_render"
            ]["uncovered_face_pixels"]
            == 0
        ),
        "case07_accessory_safe": False,
        "case08_target_expression_preserved": bool(
            next(r for r in rows if r["case"] == "case08")[
                "mouth_identity_expression_decomposition"
            ]["target_expression_within_engineering_bound"]
            and next(r for r in rows if r["case"] == "case08")[
                "mouth_identity_expression_decomposition"
            ]["mouth_texture_expression_compatible"]
        ),
        "canonical_L_machine_prequalified": False,
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
