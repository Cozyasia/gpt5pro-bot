"""Public-fixture 1856x2304 transfer ablation. No human acceptance claim.

Patches are scoped to this offline process and restored in finally. Production
transfer_attempt and its two-attempt routing are not changed by this script.
"""

from __future__ import annotations
import argparse
import json
import resource
from pathlib import Path
import cv2
import numpy as np
from neyrobot_prod import dense68_engine_v265 as e
from neyrobot_prod import selfie_v253_yunet_source_pixels as v
from neyrobot_prod import selfie_v263_dense_identity_lock as d
from neyrobot_prod import selfie_v265_single_owner as owner
from scripts.v265_source_fidelity_calibration import landmarks
from neyrobot_prod.v265_source_fidelity import morphology


def run(args):
    cv2.setNumThreads(1)
    cv2.setRNGSeed(0)
    source = cv2.imread(str(args.fixtures / "verify_now_2024.jpg"))
    right = cv2.imread(str(args.fixtures / "verify_curie.jpg"))
    from scripts.v265_strict_stability_probe import _stage1_from_target

    stage_bytes = _stage1_from_target(
        (args.fixtures / "verify_now_2024.jpg").read_bytes(), args.models / "yunet.onnx"
    )
    stage = cv2.imdecode(np.frombuffer(stage_bytes, np.uint8), 1)
    firewall = round(stage.shape[1] * 0.55)
    stage[:, firewall:] = cv2.resize(right, (stage.shape[1] - firewall, stage.shape[0]))
    sb, s5 = v._yunet_face(source, args.models / "yunet.onnx", label="ablation_source")
    tb, t5 = v._yunet_face(
        stage[:, :firewall], args.models / "yunet.onnx", label="ablation_target"
    )
    sp = landmarks(source, args.models)
    tp = landmarks(stage, args.models, True)
    transform, _ = d._similarity_transform(s5, t5)
    projected = e._project_points(transform, sp)
    original_compose = e._structure_first_compose_roi
    original_mask = e._landmark_anatomy_mask
    source_bytes = cv2.imencode(".png", source)[1].tobytes()
    stage_bytes = cv2.imencode(".png", stage)[1].tobytes()
    results = []
    try:
        for mode in ["baseline", "source_core", "source_core_dense_mask"]:
            for strict in [False, True]:
                desired = d._desired_identity_geometry(
                    projected, tp, min(tb[2:4]), strict=strict
                )
                if mode != "baseline":

                    def compose(corrected, target, mask, face_min, *, strict):
                        out = e._source_core_compose_roi_experiment(
                            corrected, target, mask, face_min
                        )
                        return out, "offline_source_core", 0, 0, 0

                    e._structure_first_compose_roi = compose
                else:
                    e._structure_first_compose_roi = original_compose
                if mode == "source_core_dense_mask":
                    e._landmark_anatomy_mask = lambda shape, bbox, points, firewall: e._dense_anatomy_mask_experiment(
                        shape, desired, firewall
                    )
                else:
                    e._landmark_anatomy_mask = original_mask
                out, metrics, expected = e.transfer_attempt(
                    stage_bytes,
                    source_bytes,
                    args.models / "yunet.onnx",
                    args.models / "pipnet.onnx",
                    args.models / "mobileface.onnx",
                    strict=strict,
                )
                post, post_metrics = e.apply_ocular_lock(
                    stage_bytes,
                    out,
                    source_bytes,
                    expected,
                    args.models / "yunet.onnx",
                    args.models / "pipnet.onnx",
                    args.models / "mobileface.onnx",
                    metrics,
                )
                selected, selected_metrics, phase, passed, failures = (
                    owner._select_ocular_candidate(
                        mode, out, metrics, post, post_metrics
                    )
                )
                image = cv2.imdecode(np.frombuffer(selected, np.uint8), 1)
                fp = landmarks(image, args.models, True)
                locked = np.array_equal(image[:, firewall:], stage[:, firewall:])
                if not locked:
                    raise AssertionError("PERSON-B firewall changed")
                results.append(
                    {
                        "mode": mode,
                        "strict": strict,
                        "phase": phase,
                        "old_gate_pass": passed,
                        "old_gate_failures": failures,
                        "metrics": selected_metrics,
                        "source_morphology": morphology(sp, fp),
                        "person_b_firewall_unchanged": bool(locked),
                    }
                )
    finally:
        e._structure_first_compose_roi = original_compose
        e._landmark_anatomy_mask = original_mask
    report = {
        "dimensions": [1856, 2304],
        "generated_positive": False,
        "human_approved": False,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "results": results,
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--fixtures", type=Path, required=True)
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args())
