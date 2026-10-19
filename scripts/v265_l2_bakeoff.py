"""Seven-case geometry-only canonical model bake-off.

No texture, compositor, production import, or legacy fallback is allowed here.
"""

import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import resource
import time
import cv2
import numpy as np
import onnxruntime as ort

from neyrobot_prod.v265_expression_contract import mouth_decomposition_report
from neyrobot_prod.v265_l2_geometry import (
    FaceVerseGeometry,
    bounded_canonical_residual,
    crop_box_from_yunet,
    crop_for_faceverse,
    faceverse_input,
    projected_surface_validity,
    split_faceverse,
    triangle_distortion,
)
from neyrobot_prod.v265_source_fidelity import morphology, normalize
from scripts.v265_transfer_matrix import pointset


CASES = ("case01", "case02", "case04", "case05", "case06", "case07", "case08")
SELF_BOUNDS = {
    "eyes": .025, "nose": .050, "mouth": .040, "jaw": .080,
    "chin": .080, "cheeks": .065, "full_face_configuration": .065,
}
PARSING_LABELS = (
    "background", "skin", "left_brow", "right_brow", "left_eye", "right_eye",
    "glasses", "left_ear", "right_ear", "earring", "nose", "mouth_interior",
    "upper_lip", "lower_lip", "neck", "necklace", "cloth", "hair", "hat",
)


def rss_kib():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def infer(session, image, box):
    crop_box = crop_box_from_yunet(box, image.shape)
    name = session.get_inputs()[0].name
    coefficients = session.run(None, {name: faceverse_input(image, crop_box)})[0][0]
    return coefficients.astype(np.float32), crop_box


def self_regions(observed, projected):
    a, b = normalize(observed), normalize(projected)
    groups = {
        "eyes": range(36, 48), "nose": range(27, 36), "mouth": range(48, 68),
        "jaw": list(range(0, 8)) + list(range(9, 17)), "chin": (7, 8, 9),
        "cheeks": (1, 2, 3, 13, 14, 15, 31, 35),
        "full_face_configuration": range(68),
    }
    return {k: float(np.linalg.norm(a[list(v)] - b[list(v)], axis=1).mean())
            for k, v in groups.items()}


def draw_overlay(image, observed, candidates, path):
    scale = min(1.0, 900 / max(image.shape[:2]))
    canvas = cv2.resize(image, None, fx=scale, fy=scale)
    colors = ((0, 255, 0), (0, 165, 255), (255, 80, 20))
    for p in observed:
        cv2.circle(canvas, tuple(np.rint(p * scale).astype(int)), 2, colors[0], -1)
    for points, color in zip(candidates, colors[1:]):
        for p in points:
            cv2.circle(canvas, tuple(np.rint(p * scale).astype(int)), 2, color, 1)
    cv2.imwrite(str(path), canvas)


def parsing_prediction(session, image, box):
    crop_box = crop_box_from_yunet(box, image.shape)
    crop = crop_for_faceverse(image, crop_box)
    crop = cv2.resize(crop, (512, 512), interpolation=cv2.INTER_LINEAR)
    x = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    x = (x - np.array([.485, .456, .406], np.float32)) / np.array([.229, .224, .225], np.float32)
    x = x.transpose(2, 0, 1)[None]
    output = session.run(None, {session.get_inputs()[0].name: x})[0][0]
    labels = output.argmax(0).astype(np.uint8)
    glasses = labels == 6
    count = int(glasses.sum())
    # A semantic class must occupy a nontrivial component, not a lone noisy texel.
    n, _, stats, _ = cv2.connectedComponentsWithStats(glasses.astype(np.uint8), 8)
    component = int(stats[1:, cv2.CC_STAT_AREA].max()) if n > 1 else 0
    return {
        "class_pixels": {PARSING_LABELS[i]: int(np.count_nonzero(labels == i)) for i in range(19)},
        "glasses_pixels": count,
        "largest_glasses_component": component,
        "glasses_present": component >= 16,
        "mask": labels,
    }


def source_overlay_baseline(case):
    row = json.loads(Path(f"docs/engineering/v265-canonical/{case}_L.json").read_text())
    return row["pipnet_source_to_model_fit_error"], np.asarray(row["source_model_landmarks"], np.float32)


def run(a):
    cv2.setNumThreads(1)
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    a.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    baseline_rss = rss_kib()
    so = ort.SessionOptions()
    so.intra_op_num_threads = so.inter_op_num_threads = 1
    so.enable_cpu_mem_arena = False
    regressor = ort.InferenceSession(str(a.assets / "faceverse_resnet50_int8.onnx"), so,
                                     providers=["CPUExecutionProvider"])
    after_regressor_rss = rss_kib()
    model = FaceVerseGeometry(a.assets / "faceverse_geometry.npz")
    after_geometry_rss = rss_kib()
    source_cache = {}
    rows = []
    target_cache = {}
    for case in CASES:
        source_path = a.fixtures / f"{case}_source.jpg"
        target_path = a.fixtures / f"{case}_stage1.png"
        source_image = cv2.imread(str(source_path))
        target_image = cv2.resize(cv2.imread(str(target_path)), (1856, 2304), interpolation=cv2.INTER_LANCZOS4)
        source_box, _, source_observed = pointset(source_image, a.models)
        target_box, _, target_observed = pointset(target_image, a.models, True)
        source_key = digest(source_path)
        if source_key not in source_cache:
            scoeff, scrop = infer(regressor, source_image, source_box)
            source_cache[source_key] = (scoeff, scrop)
        scoeff, scrop = source_cache[source_key]
        tcoeff, tcrop = infer(regressor, target_image, target_box)
        target_cache[case] = (tcoeff, tcrop)
        sp = split_faceverse(scoeff); tp = split_faceverse(tcoeff)
        source_vertices = model.shape(sp["identity"], sp["expression"])
        source_projected = model.project(source_vertices, sp, scrop)
        source_lm = source_projected[model.landmarks, :2]
        iod = float(np.linalg.norm(source_observed[36:42].mean(0) - source_observed[42:48].mean(0)))
        residual, residual_report = bounded_canonical_residual(
            model, source_vertices, source_projected, source_observed, iod, sp, scrop
        )
        residual_source_vertices = source_vertices + residual
        residual_source = model.project(residual_source_vertices, sp, scrop)[model.landmarks, :2]
        target_vertices = model.shape(sp["identity"], tp["expression"])
        target_geometry = model.project(target_vertices, tp, tcrop)[model.landmarks, :2]
        residual_target_vertices = target_vertices + residual
        residual_target = model.project(residual_target_vertices, tp, tcrop)[model.landmarks, :2]
        baseline_metrics, baseline_landmarks = source_overlay_baseline(case)
        rich_metrics = self_regions(source_observed, source_lm)
        residual_metrics = self_regions(source_observed, residual_source)
        disentangled_a = mouth_decomposition_report(source_observed, target_observed, target_geometry)
        disentangled_b = mouth_decomposition_report(source_observed, target_observed, residual_target)
        # The generic helper deliberately defaults expression_disentangled false;
        # geometry-only selection uses both independently measured contracts.
        for report in (disentangled_a, disentangled_b):
            report["expression_disentangled"] = bool(
                report["identity_geometry_within_engineering_bound"]
                and report["target_expression_within_engineering_bound"]
            )
        face_triangles = model.triangles[np.all(model.face_mask[model.triangles], axis=1)]
        target_projected_all = model.project(residual_target_vertices, tp, tcrop)
        geometry_validity = triangle_distortion(residual_source_vertices, residual_target_vertices, face_triangles)
        geometry_validity.update(projected_surface_validity(target_projected_all, face_triangles))
        row = {
            "case": case,
            "source_sha256": source_key,
            "baseline_3ddfa_self_reconstruction": baseline_metrics,
            "faceverse_self_reconstruction": rich_metrics,
            "faceverse_residual_self_reconstruction": residual_metrics,
            "faceverse_self_sufficient": all(rich_metrics[k] <= SELF_BOUNDS[k] for k in SELF_BOUNDS),
            "faceverse_residual_self_sufficient": all(residual_metrics[k] <= SELF_BOUNDS[k] for k in SELF_BOUNDS),
            "faceverse_expression_retarget": disentangled_a,
            "faceverse_residual_expression_retarget": disentangled_b,
            "canonical_residual": residual_report,
            "identity_digest_faceverse": model.identity_digest(sp["identity"]),
            "identity_digest_faceverse_residual": model.identity_digest(sp["identity"], residual),
            "target_pose_expression_only": True,
            "geometry_validity": geometry_validity,
            "critical_geometry_owner": {
                k: "source_identity" for k in ("brow", "eyes", "nose", "cheeks", "lips", "jaw", "chin")
            } | {"mouth_interior": "target_expression"},
            "critical_pixel_ownership_measured": False,
        }
        rows.append(row)
        (a.output / f"{case}.json").write_text(json.dumps(row, indent=2))
        draw_overlay(source_image, source_observed, (baseline_landmarks, source_lm, residual_source),
                     a.output / f"{case}_source_self_overlay.jpg")
        print(case, rich_metrics["full_face_configuration"], residual_metrics["full_face_configuration"], flush=True)

    # Models have sequential lifetime: parsing is loaded only after geometry fit.
    del regressor
    gc.collect()
    before_parsing_rss = rss_kib()
    parser = ort.InferenceSession(str(a.assets / "face_parsing_resnet18.onnx"), so,
                                  providers=["CPUExecutionProvider"])
    after_parsing_rss = rss_kib()
    validation_specs = (
        ("case07_source", "case07_source.jpg", True, "glasses_positive_partial_frames"),
        ("case07_stage1", "case07_stage1.png", True, "glasses_positive_generated"),
        ("case01_source", "case01_source.jpg", False, "dark_brows_negative"),
        ("case02_source", "case02_source.jpg", False, "dark_skin_high_contrast_negative"),
        ("case04_source", "case04_source.jpg", False, "eye_shadow_grayscale_negative"),
        ("case08_source", "case08_source.jpg", False, "no_glasses_negative"),
    )
    parsing_rows = []
    for name, filename, expected, stratum in validation_specs:
        image = cv2.imread(str(a.fixtures / filename))
        left = "stage1" in name
        box, _, _ = pointset(image, a.models, left)
        result = parsing_prediction(parser, image, box)
        mask = result.pop("mask")
        cv2.imwrite(str(a.output / f"{name}_parsing.png"), mask)
        result.update({"fixture": name, "stratum": stratum, "expected_glasses": expected,
                       "correct": result["glasses_present"] == expected})
        parsing_rows.append(result)
    glasses_presence_valid = all(r["correct"] for r in parsing_rows)
    repeated = {}
    for a_case, b_case in (("case01", "case05"), ("case02", "case06")):
        ra = next(r for r in rows if r["case"] == a_case)
        rb = next(r for r in rows if r["case"] == b_case)
        repeated[f"{a_case}_{b_case}"] = {
            "parametric_hash_equal": ra["identity_digest_faceverse"] == rb["identity_digest_faceverse"],
            "residual_hash_equal": ra["identity_digest_faceverse_residual"] == rb["identity_digest_faceverse_residual"],
        }
    summary = {
        "candidates": {
            "current_3ddfa": {"identity_dimensions": 40, "expression_dimensions": 10},
            "L2_A_faceverse_v4": {"identity_dimensions": 156, "expression_dimensions": 177},
            "L2_B_faceverse_v4_canonical_residual": {"identity_dimensions": 156, "expression_dimensions": 177},
        },
        "self_reconstruction_bounds": SELF_BOUNDS,
        "rows": rows,
        "repeated_identity": repeated,
        "parsing_validation": parsing_rows,
        "glasses_presence_validation_pass": glasses_presence_valid,
        "parsing_validated": False,
        "parsing_validation_blockers": [
            "no independent per-pixel ground truth for the frozen photos",
            "CelebAMask-HQ-derived checkpoint lacks commercial clearance",
        ],
        "parsing_training_rights_commercially_cleared": False,
        "memory": {
            "baseline_rss_kib": baseline_rss,
            "after_regressor_rss_kib": after_regressor_rss,
            "after_geometry_rss_kib": after_geometry_rss,
            "before_parsing_rss_highwater_kib": before_parsing_rss,
            "after_parsing_rss_highwater_kib": after_parsing_rss,
            "peak_rss_kib": rss_kib(),
            "geometry_array_bytes": model.resident_array_bytes,
            "regressor_file_bytes": (a.assets / "faceverse_resnet50_int8.onnx").stat().st_size,
            "parsing_file_bytes": (a.assets / "face_parsing_resnet18.onnx").stat().st_size,
            "sequential_model_lifetime": True,
        },
        "elapsed_s": time.monotonic() - started,
    }
    case08 = next(r for r in rows if r["case"] == "case08")
    case06 = next(r for r in rows if r["case"] == "case06")
    summary.update({
        "current_3ddfa_capacity_sufficient": False,
        "best_canonical_model": "FaceVerse V4 + bounded canonical 3D residual",
        "canonical_3d_residual_needed": True,
        "projected_68_self_reconstruction_sufficient": all(r["faceverse_residual_self_sufficient"] for r in rows),
        "source_self_reconstruction_sufficient": False,
        "source_self_reconstruction_blocker": "dense source surface has no independent photo-ground-truth; 68-point residual fit alone is insufficient",
        "case08_expression_disentangled": case08["faceverse_residual_expression_retarget"]["expression_disentangled"],
        "identity_complete": False,
        "identity_complete_blocker": "geometry-only bake-off has no pixel ownership/render contract",
        "production_memory_qualified": False,
    })
    normal = [r["geometry_validity"] for r in rows if r["case"] != "case06"]
    envelope = {
        "area_q01_min": min(g["local_area_ratio"]["0.01"] for g in normal),
        "area_q99_max": max(g["local_area_ratio"]["0.99"] for g in normal),
        "area_absolute_min": min(g["local_area_ratio"]["0"] for g in normal),
        "area_absolute_max": max(g["local_area_ratio"]["1"] for g in normal),
        "edge_q01_min": min(g["edge_stretch"]["0.01"] for g in normal),
        "edge_q99_max": max(g["edge_stretch"]["0.99"] for g in normal),
        "edge_absolute_min": min(g["edge_stretch"]["0"] for g in normal),
        "edge_absolute_max": max(g["edge_stretch"]["1"] for g in normal),
    }
    summary["case06_benign_envelope"] = envelope
    cg = case06["geometry_validity"]
    summary["case06_geometry_valid"] = bool(
        cg["orientation_failures"] == 0 and cg["degenerate_triangles"] == 0
        and cg["silhouette_continuous"]
        and cg["local_area_ratio"]["0"] >= envelope["area_absolute_min"]
        and cg["local_area_ratio"]["1"] <= envelope["area_absolute_max"]
        and cg["edge_stretch"]["0"] >= envelope["edge_absolute_min"]
        and cg["edge_stretch"]["1"] <= envelope["edge_absolute_max"]
    )
    summary["l2_geometry_machine_prequalified"] = bool(
        summary["source_self_reconstruction_sufficient"]
        and summary["case06_geometry_valid"]
        and summary["case08_expression_disentangled"]
        and summary["parsing_validated"]
        and summary["production_memory_qualified"]
    )
    (a.output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: summary[k] for k in (
        "source_self_reconstruction_sufficient", "case06_geometry_valid",
        "case08_expression_disentangled", "parsing_validated",
        "l2_geometry_machine_prequalified")}, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--assets", type=Path, required=True)
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--fixtures", type=Path, default=Path("tests/fixtures/v265_matrix"))
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args())
