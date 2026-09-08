"""Frozen generated Stage-1 V265 A-E matrix, one isolated process per variant.

ImageGen fixtures are NOT production Gemini fixtures. Stage-1 normalization to
1856x2304 is performed exactly once and the resulting PNG hash is asserted by
all variants. Source image pixels are never artificially enlarged for preflight.
"""

from __future__ import annotations
import argparse, hashlib, json, os, resource, subprocess, sys, threading, time
from pathlib import Path
import cv2
import numpy as np
from neyrobot_prod import dense68_engine_v265 as e
from neyrobot_prod import selfie_v253_yunet_source_pixels as v
from neyrobot_prod import selfie_v263_dense_identity_lock as d
from neyrobot_prod import selfie_v265_single_owner as owner
from neyrobot_prod import v265_strict_runtime_safety as memory
from neyrobot_prod import v265_transfer_lab as lab
from neyrobot_prod.v265_source_fidelity import morphology


class MemorySampler:
    def __init__(self):
        self.peak = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self):
        while not self.stop.is_set():
            current = memory._read_int("/sys/fs/cgroup/memory.current")
            if current is not None:
                self.peak = max(self.peak, current)
            self.stop.wait(0.02)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def encode(a):
    return cv2.imencode(".png", a, [cv2.IMWRITE_PNG_COMPRESSION, 2])[1].tobytes()


def read(path):
    return cv2.imread(str(path))


def pointset(im, models, left=False):
    box, pts = v._yunet_face(
        im[:, : round(im.shape[1] * 0.55)] if left else im,
        models / "yunet.onnx",
        label="matrix",
    )
    dense = d._dense_landmarks_68(im, box, models / "pipnet.onnx", label="matrix")
    return box, pts, dense


def pose_signature(points):
    # Observable 2D proxy only. Nose asymmetry confounds identity and yaw.
    a, b = points[36:42].mean(0), points[42:48].mean(0)
    axis = b - a
    iod = np.linalg.norm(axis)
    u = axis / iod
    down = np.array([-u[1], u[0]])
    return {
        "roll_deg": float(np.degrees(np.arctan2(axis[1], axis[0]))),
        "nose_offset_proxy": float((points[30] - (a + b) / 2) @ u / iod),
        "mouth_aperture_proxy": float(np.linalg.norm(points[66] - points[62]) / iod),
    }


def worker(args):
    cv2.setNumThreads(1)
    cv2.setRNGSeed(0)
    started = time.monotonic()
    pid = os.getpid()
    source_b = (args.fixtures / (args.case + "_source.jpg")).read_bytes()
    stage_b = (args.output / args.case / "stage1.png").read_bytes()
    target = cv2.imdecode(np.frombuffer(stage_b, np.uint8), 1)
    source = cv2.imdecode(np.frombuffer(source_b, np.uint8), 1)
    sb, s5, sd = pointset(source, args.models)
    tb, t5, td = pointset(target, args.models, True)
    matrix, _ = d._similarity_transform(s5, t5)
    projected = e._project_points(matrix, sd)
    face_min = float(min(tb[2:4]))
    firewall = round(target.shape[1] * 0.55)
    support = lab.full_face_support(target.shape, td, firewall)
    used_support = (
        support
        if args.mode in ("B_mask", "D_mask_core", "E_mask_frequency", "T_exact_field")
        else e._landmark_anatomy_mask(target.shape, tb, t5, firewall)
    )
    pose_target = pose_signature(td)
    results = []
    outputs = {}
    before_cgroup = memory._memory_state()
    with lab.variant(
        args.mode,
        sd,
        td,
        projected,
        face_min,
        source_shape=source.shape,
        target_shape=target.shape,
    ) as shape_diagnostics:
        for strict in [False, True]:
            if strict:
                memory._strict_preflight()
            pre, pm, desired = e.transfer_attempt(
                stage_b,
                source_b,
                args.models / "yunet.onnx",
                args.models / "pipnet.onnx",
                args.models / "mobileface.onnx",
                strict=strict,
            )
            post, qm = e.apply_ocular_lock(
                stage_b,
                pre,
                source_b,
                desired,
                args.models / "yunet.onnx",
                args.models / "pipnet.onnx",
                args.models / "mobileface.onnx",
                pm,
            )
            selected, metrics, phase, passed, failures = owner._select_ocular_candidate(
                args.mode, pre, pm, post, qm
            )
            del pre, post
            image = cv2.imdecode(np.frombuffer(selected, np.uint8), 1)
            _, _, fd = pointset(image, args.models, True)
            source_morph = morphology(sd, fd)
            from neyrobot_prod.v265_shape_lab import configuration

            config_source, config_final = configuration(sd), configuration(fd)
            if args.mode in (
                "F_jaw_shape",
                "G_face_shape",
                "H_jaw_silhouette",
                "I_ortho_jaw",
                "J_ortho_face",
                "K_ortho_silhouette",
            ):
                owned = td.copy()
                owned[:17] = desired[:17]
                support = lab.full_face_support(target.shape, owned, firewall)
                if args.mode in ("H_jaw_silhouette", "K_ortho_silhouette"):
                    support = cv2.bitwise_or(
                        support, lab.full_face_support(target.shape, td, firewall)
                    )
                used_support = support

            pose = pose_signature(fd)
            b_safe = np.array_equal(image[:, firewall:], target[:, firewall:])
            # Neck sample is in face coordinates, beyond chin away from eye midpoint.
            eye_mid = (td[36:42].mean(0) + td[42:48].mean(0)) / 2
            down = td[8] - eye_mid
            down /= np.linalg.norm(down)
            neck = td[8] + down * face_min * 0.12
            nx, ny = np.rint(neck).astype(int)
            neck_safe = np.array_equal(
                image[max(0, ny - 4) : ny + 5, max(0, nx - 4) : nx + 5],
                target[max(0, ny - 4) : ny + 5, max(0, nx - 4) : nx + 5],
            )
            if not b_safe:
                raise AssertionError("PERSON-B firewall mutation")
            if not neck_safe:
                raise AssertionError("neck sample mutation")
            # Row-at-a-time verification adds no full-frame temporary array.
            outside_changes = sum(
                int(
                    np.count_nonzero(
                        np.any(image[y] != target[y], axis=1) & (support[y] == 0)
                    )
                )
                for y in range(target.shape[0])
            )
            if (
                args.mode
                in (
                    "D_mask_core",
                    "E_mask_frequency",
                    "T_exact_field",
                    "F_jaw_shape",
                    "G_face_shape",
                    "H_jaw_silhouette",
                    "I_ortho_jaw",
                    "J_ortho_face",
                    "K_ortho_silhouette",
                )
                and outside_changes
            ):
                raise AssertionError("source core escaped semantic face support")
            name = "strict" if strict else "standard"
            outpath = args.output / args.case / (args.mode + "_" + name + ".png")
            outpath.write_bytes(selected)
            outputs[name] = (selected, metrics, passed)
            results.append(
                {
                    "path": name,
                    "phase": phase,
                    "old_gate_pass": passed,
                    "old_gate_failures": failures,
                    "morphology": source_morph,
                    "source_configuration_2d": config_source,
                    "candidate_configuration_2d": config_final,
                    "metrics": metrics,
                    "pose_proxy": pose,
                    "target_pose_proxy": pose_target,
                    "roll_delta_deg": abs(pose["roll_deg"] - pose_target["roll_deg"]),
                    "person_b_unchanged": bool(b_safe),
                    "neck_sample_unchanged": bool(neck_safe),
                    "changed_pixels_outside_dense_support": outside_changes,
                    "png_sha256": sha(selected),
                    "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                }
            )
            del image, selected
            memory._reclaim_before_strict()
    standard = outputs["standard"]
    strict = outputs["strict"]
    decision = owner._final_candidate_decision(
        standard[2], standard[1], strict[2], strict[1]
    )
    # Even a rejected candidate remains inspectable; never call this production delivery.
    inspect_name = decision if decision != "reject" else "standard"
    (args.output / args.case / (args.mode + "_selected.png")).write_bytes(
        outputs[inspect_name][0]
    )
    coverage_points = (
        owned
        if args.mode
        in (
            "F_jaw_shape",
            "G_face_shape",
            "H_jaw_silhouette",
            "I_ortho_jaw",
            "J_ortho_face",
            "K_ortho_silhouette",
        )
        else td
    )
    coverage = {
        r: sum(
            int(
                used_support[round(coverage_points[i, 1]), round(coverage_points[i, 0])]
                > 80
            )
            for i in ids
        )
        for r, ids in {
            "jaw": range(17),
            "chin": (7, 8, 9),
            "lip": range(48, 68),
        }.items()
    }
    report = {
        "case": args.case,
        "mode": args.mode,
        "stage1_sha256": sha(stage_b),
        "source_sha256": sha(source_b),
        "generated_by": "ImageGen, not production Gemini",
        "dimensions": [1856, 2304],
        "decision": decision,
        "inspection_candidate": inspect_name,
        "pid_stable": pid == os.getpid(),
        "daemon_context": threading.current_thread().daemon,
        "elapsed_s": time.monotonic() - started,
        "cgroup_before": before_cgroup,
        "cgroup_after": memory._memory_state(),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "sampled_cgroup_peak_bytes": args.sampler.peak,
        "cgroup_sampling_interval_ms": 20,
        "qualification": "offline only; no production daemon baseline load",
        "mask_coverage": coverage,
        "shape_diagnostics": shape_diagnostics,
        "results": results,
    }
    (args.output / args.case / (args.mode + ".json")).write_text(
        json.dumps(report, indent=2, sort_keys=True)
    )
    print("MATRIX_RESULT", json.dumps(report, sort_keys=True))


def run(args):
    args.output.mkdir(exist_ok=True, parents=True)
    cases = [args.case] if args.case else ["case01", "case02", "case04"]
    failed = []
    for case in cases:
        folder = args.output / case
        folder.mkdir(exist_ok=True)
        stage = read(args.fixtures / (case + "_stage1.png"))
        frozen = encode(
            cv2.resize(stage, (1856, 2304), interpolation=cv2.INTER_LANCZOS4)
        )
        destination = folder / "stage1.png"
        if destination.exists() and destination.read_bytes() != frozen:
            raise ValueError("frozen Stage-1 changed")
        destination.write_bytes(frozen)
        for mode in lab.MODES:
            command = [
                sys.executable,
                "-m",
                "scripts.v265_transfer_matrix",
                "--worker",
                "--case",
                case,
                "--mode",
                mode,
                "--fixtures",
                str(args.fixtures),
                "--models",
                str(args.models),
                "--output",
                str(args.output),
            ]
            if args.daemon:
                command.append("--daemon")
            with (folder / (mode + ".log")).open("w") as log:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode:
                failed.append((case, mode, result.returncode))
                print("MATRIX_FAILED", case, mode, result.returncode, flush=True)
            else:
                print("MATRIX_DONE", case, mode, flush=True)
    if failed:
        raise RuntimeError("matrix workers failed: " + repr(failed))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--fixtures", type=Path, default=Path("tests/fixtures/v265_matrix"))
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--case")
    p.add_argument("--mode")
    p.add_argument("--worker", action="store_true")
    p.add_argument("--daemon", action="store_true")
    a = p.parse_args()
    a.sampler = MemorySampler()
    if a.worker:
        a.sampler.thread.start()
    if a.worker and a.daemon:
        errors = []

        def target():
            try:
                worker(a)
            except BaseException as ex:
                errors.append(ex)

        t = threading.Thread(target=target, daemon=True)
        t.start()
        t.join()
        if errors:
            raise errors[0]
    elif a.worker:
        worker(a)
    else:
        run(a)
    a.sampler.stop.set()
