"""Geometry-only withheld-view evaluation. No fit to B and no renderer/fallback."""

import argparse
import json
from pathlib import Path
import numpy as np
from .ingest import finite, require, array_hash


def project(v, k, r, t):
    camera = v @ r.T + t
    require((camera[:, 2] > 1e-6).all(), "surface behind camera")
    screen = camera @ k.T
    return screen[:, :2] / screen[:, 2, None]


def topology_metrics(v, reference, triangles):
    p, g = v[triangles], reference[triangles]
    pn = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    gn = np.cross(g[:, 1] - g[:, 0], g[:, 2] - g[:, 0])
    ga = np.linalg.norm(gn, axis=1)
    require((ga > 1e-12).all(), "invalid reference topology")
    ratio = np.linalg.norm(pn, axis=1) / ga
    edges = np.unique(
        np.sort(
            np.concatenate(
                [triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]]
            ),
            axis=1,
        ),
        axis=0,
    )
    length = lambda x: np.linalg.norm(x[edges[:, 1]] - x[edges[:, 0]], axis=1)
    stretch = length(v) / length(reference)

    def aspect(x):
        p = x[triangles]
        ls = ((p - np.roll(p, 1, axis=1)) ** 2).sum(2).sum(1)
        area = np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
        return ls / np.maximum(area, 1e-12)

    def dist(x):
        return dict(
            zip(
                ["min", "p01", "median", "p99", "max"],
                np.quantile(x, [0, 0.01, 0.5, 0.99, 1]).tolist(),
            )
        )

    return {
        "orientation_failures": int(((pn * gn).sum(1) <= 0).sum()),
        "local_area_ratio": dist(ratio),
        "edge_stretch": dist(stretch),
        "aspect_distortion": dist(aspect(v) / aspect(reference)),
    }


def mouth_measures(v, ids):
    # Semantic landmarks are supplier-corresponded, never inferred from texture.
    p = {name: v[i] for name, i in ids.items()}
    dist = lambda a, b: float(np.linalg.norm(p[a] - p[b]))
    width = dist("left_corner", "right_corner")
    require(width > 1e-6, "invalid mouth width")
    return {
        "width": width,
        "lip_ratio": dist("upper_outer", "upper_inner")
        / max(dist("lower_outer", "lower_inner"), 1e-6),
        "philtrum": dist("nose_base", "upper_outer") / width,
        "mouth_nose": width / max(dist("nose_left", "nose_right"), 1e-6),
        "mouth_chin": dist("lower_outer", "chin") / width,
        "opening": dist("upper_inner", "lower_inner") / width,
        "corner_elevation": float(
            (
                (p["upper_inner"][1] + p["lower_inner"][1]) / 2
                - (p["left_corner"][1] + p["right_corner"][1]) / 2
            )
            / width
        ),
    }


def evaluate_pair(
    canonical_a,
    neutral_gt,
    expression_basis,
    target_expression,
    withheld_b,
    k,
    r,
    t,
    triangles,
    regions,
    visible,
    boundary,
    mouth_ids,
    envelope=None,
    evidence=None,
):
    """A-derived canonical input is reused verbatim; B contributes controls and GT only.

    Withheld B geometry must be independent ground truth, not a fit of this model.
    Calibration thresholds are external, derived from a sealed benign validation set.
    Missing calibrated envelope returns UNQUALIFIED even for identical geometry.
    """
    a = finite(canonical_a, neutral_gt.shape)
    finite(withheld_b, a.shape)
    out = a + np.einsum("e,enc->nc", target_expression, expression_basis)
    pa = project(out, k, r, t)
    pb = project(withheld_b, k, r, t)
    scale = np.linalg.norm(np.ptp(pb[visible], axis=0))
    require(scale > 0, "zero projected extent")
    metrics = {}
    for name, idx in {**regions, "whole_face": np.arange(len(a))}.items():
        idx = np.asarray(idx)
        idx = idx[visible[idx]]
        require(len(idx) > 0, "unobservable region " + name)
        metrics[name] = {
            "neutral_rmse_m": float(np.sqrt(np.mean((a[idx] - neutral_gt[idx]) ** 2))),
            "withheld_projected_nme": float(
                np.linalg.norm(pa[idx] - pb[idx], axis=1).mean() / scale
            ),
        }
    # Corresponded visible contour comparison: no post-fit vertex culling.
    require(
        len(boundary) > 0 and visible[boundary].all(),
        "missing visible silhouette boundary",
    )
    metrics["silhouette_nme"] = float(
        np.linalg.norm(pa[boundary] - pb[boundary], axis=1).mean() / scale
    )
    geom = topology_metrics(out, withheld_b, triangles)
    intrinsic_pred, intrinsic_gt = mouth_measures(a, mouth_ids), mouth_measures(
        neutral_gt, mouth_ids
    )
    expr_pred, expr_gt = mouth_measures(out, mouth_ids), mouth_measures(
        withheld_b, mouth_ids
    )
    intrinsic_errors = {
        x: abs(intrinsic_pred[x] - intrinsic_gt[x])
        for x in ["width", "lip_ratio", "philtrum", "mouth_nose", "mouth_chin"]
    }
    expression_errors = {
        x: abs(expr_pred[x] - expr_gt[x]) for x in ["opening", "corner_elevation"]
    }
    result = {
        "source_canonical_hash": array_hash(a),
        "regions": metrics,
        "geometry": geom,
        "intrinsic_mouth_errors": intrinsic_errors,
        "expression_errors": expression_errors,
        "case06": "UNQUALIFIED",
        "case08": "UNQUALIFIED",
        "machine_prequalified": False,
        "limitations": [
            "contour correspondence is not independent pixel-hole validation",
            "teeth visibility and smile coefficient require independent labels",
        ],
    }
    if envelope is not None:
        # Never invent a benign envelope or calibrate on the test cases.
        require(
            envelope["calibration_split"] == "validation"
            and envelope["approved"] is True
            and bool(envelope["source_sha256"]),
            "unapproved envelope",
        )
        result["case06"] = (
            "PASS"
            if (
                geom["orientation_failures"] == 0
                and geom["local_area_ratio"]["min"] >= envelope["area_min"]
                and geom["local_area_ratio"]["max"] <= envelope["area_max"]
                and geom["edge_stretch"]["max"] <= envelope["edge_max"]
                and geom["edge_stretch"]["min"] >= envelope["edge_min"]
                and metrics["silhouette_nme"] <= envelope["silhouette_nme"]
            )
            else "FAIL"
        )
        # Geometry screen only; full case06 also needs actual visible-surface holes check.
        result["case06_scope"] = (
            "geometry screen; critical pixel holes remain unqualified"
        )
        if evidence is not None:
            coverage = np.asarray(evidence["render_coverage"], dtype=bool)
            critical = np.asarray(evidence["visible_critical_gt"], dtype=bool)
            require(
                coverage.shape == critical.shape and critical.any(),
                "invalid independent coverage masks",
            )
            holes = int(np.count_nonzero(critical & ~coverage))
            result["critical_holes"] = holes
            result["case06"] = (
                "PASS" if result["case06"] == "PASS" and holes == 0 else "FAIL"
            )
            result["case06_scope"] = (
                "geometry and supplied independent visible-coverage masks"
            )
            errors = {**intrinsic_errors, **expression_errors}
            # Smile and teeth are independently measured outputs, not copied target controls.
            for key in ["smile_amount", "teeth_visibility"]:
                values = finite(evidence[key], (2,))
                errors[key] = float(abs(values[0] - values[1]))
            result["case08_errors"] = errors
            require(
                set(envelope["case08_limits"]) == set(errors),
                "incomplete case08 thresholds",
            )
            result["case08"] = (
                "PASS"
                if all(errors[k] <= envelope["case08_limits"][k] for k in errors)
                else "FAIL"
            )
            result["machine_prequalified"] = (
                result["case06"] == "PASS"
                and result["case08"] == "PASS"
                and all(
                    metrics[name]["withheld_projected_nme"]
                    <= envelope["region_nme"][name]
                    for name in regions
                )
            )
        else:
            result["case06_geometry_screen"] = result["case06"]
            result["case06"] = "UNQUALIFIED"
    return result


def cross_view_protocol(infer_identity, source_rgb, pairs):
    """Infer once from A; target photographs never enter the identity encoder.

    pairs contains independent B ground truth, pose/expression controls and metadata.
    B is not an optimisation target. The caller owns colour/crop normalisation.
    """
    canonical = np.asarray(infer_identity(source_rgb)).copy()
    frozen_hash = array_hash(canonical)
    reports = []
    for pair in pairs:
        require(pair["split"] in ["validation", "test"], "withheld split required")
        require(
            pair["source_identity_id"] == pair["target_identity_id"],
            "cross-view requires same identity",
        )
        require(
            pair["source_image_sha256"] != pair["target_image_sha256"],
            "same-photo self-fit is not cross-view",
        )
        report = evaluate_pair(canonical_a=canonical, **pair["evaluation_inputs"])
        require(
            array_hash(canonical) == frozen_hash, "target mutated canonical identity"
        )
        report["pair_id"] = pair["pair_id"]
        reports.append(report)
    require(bool(reports), "empty cross-view protocol")
    return {
        "source_canonical_hash": frozen_hash,
        "target_independent_identity": True,
        "pairs": reports,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("pair_npz")
    p.add_argument("protocol_json")
    p.add_argument("output")
    args = p.parse_args()
    cfg = json.loads(Path(args.protocol_json).read_text())
    with np.load(args.pair_npz, allow_pickle=False) as z:
        inputs = {
            k: z[k]
            for k in [
                "canonical_a",
                "neutral_gt",
                "expression_basis",
                "target_expression",
                "withheld_b",
                "k",
                "r",
                "t",
                "triangles",
                "visible",
                "boundary",
            ]
        }
        result = evaluate_pair(
            **inputs,
            regions=cfg["regions"],
            mouth_ids=cfg["mouth_ids"],
            envelope=cfg.get("envelope")
        )
    Path(args.output).write_text(json.dumps(result, indent=2))
