"""Real application construction plus V265 worker, with network disabled.

Not a warmed live-daemon qualification: Telegram initialization, live request
history and other provider models are absent. Uses dummy credentials in CI.
"""

import argparse, json, os, socket, threading
from pathlib import Path


def deny_network(*args, **kwargs):
    raise RuntimeError("network forbidden in application memory probe")


def cgroup_evidence():
    root = Path("/sys/fs/cgroup")
    return {
        name: (root / name).read_text().strip()
        for name in (
            "memory.current",
            "memory.peak",
            "memory.max",
            "memory.swap.current",
            "memory.swap.max",
            "memory.events",
        )
        if (root / name).exists()
    }


def run(a):
    if a.repetitions < 1:
        raise ValueError("repetitions must be positive")
    socket.socket.connect = deny_network
    socket.create_connection = deny_network
    import main
    from neyrobot_prod import v265_strict_runtime_safety as safety
    from scripts.v265_transfer_matrix import MemorySampler, worker

    app = main.build_application()
    state = safety._memory_state()
    print(
        "APPLICATION_BASELINE",
        json.dumps(
            {
                "memory_state": state,
                "handler_groups": len(app.handlers),
                "network_initialized": False,
                "qualification": "constructed application, not warmed production daemon",
            }
        ),
        flush=True,
    )
    a.fixtures = Path("tests/fixtures/v265_matrix")
    import cv2, resource
    from scripts.v265_transfer_matrix import pointset
    from neyrobot_prod import selfie_v263_dense_identity_lock as dense

    image = cv2.imread(str(a.fixtures / (a.case + "_source.jpg")))
    _, _, points = pointset(image, a.models)
    dense._mobileface_embedding(image, points, a.models / "mobileface.onnx")
    del image, points
    safety._reclaim_before_strict()
    warmed_state = safety._memory_state()
    canonical_components = None
    canonical_state = None
    released_state = None
    retained_geometry = None
    if a.canonical_assets:
        import numpy as np
        from neyrobot_prod.v265_canonical_lab import CanonicalModel, project
        from scripts.v265_canonical_matrix import infer

        canonical_model = CanonicalModel.load(a.canonical_assets / "canonical.npz")
        session = cv2.dnn.readNetFromONNX(str(a.canonical_assets / "regressor.onnx"))
        detector = cv2.FaceDetectorYN_create(
            str(a.models / "yunet.onnx"), "", (320, 320), 0.7
        )
        with np.load(a.canonical_assets / "canonical.npz", allow_pickle=False) as z:
            image = cv2.imread(str(a.fixtures / (a.case + "_source.jpg")))
            parameters, source_roi = infer(
                image, detector, session, z["param_mean"], z["param_std"]
            )
            target_image = cv2.resize(
                cv2.imread(str(a.fixtures / (a.case + "_stage1.png"))),
                (1856, 2304),
                interpolation=cv2.INTER_LANCZOS4,
            )
            target, target_roi = infer(
                target_image, detector, session, z["param_mean"], z["param_std"], True
            )
        retained_geometry = project(
            canonical_model.retarget(parameters, target), target.camera, target_roi
        )
        del image, target_image
        canonical_components = (canonical_model, session, detector, parameters)
        canonical_state = safety._memory_state()
        if a.canonical_residency == "scoped":
            canonical_components = None
            del canonical_model, session, detector, parameters, target
            safety._reclaim_before_strict()
            released_state = safety._memory_state()
    # Explicit resident-pressure scenario, not a claim to reproduce live traffic.
    # Keep real touched pages alive; never replace cgroup readings or the guard.
    resident_pressure = bytearray(a.resident_extra_mib * 1024 * 1024)
    for offset in range(0, len(resident_pressure), 4096):
        resident_pressure[offset] = 1
    pressure_state = safety._memory_state()
    rows = []
    for iteration in range(a.repetitions):
        a.sampler = MemorySampler()
        a.sampler.thread.start()
        errors = []
        entries = []
        original_preflight = safety._strict_preflight

        def observed_preflight():
            entries.append(safety._memory_state())
            return original_preflight()

        safety._strict_preflight = observed_preflight

        def task():
            try:
                worker(a)
            except BaseException as exc:
                errors.append(exc)
            finally:
                a.sampler.stop.set()

        try:
            thread = threading.Thread(target=task, daemon=True)
            thread.start()
            thread.join()
        finally:
            safety._strict_preflight = original_preflight
            a.sampler.thread.join()
        row = {
            "iteration": iteration,
            "strict_entry_states": entries,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "memory_after": safety._memory_state(),
            "sampled_cgroup_peak": a.sampler.peak,
        }
        if errors:
            exc = errors[0]
            if isinstance(
                exc, RuntimeError
            ) and "insufficient container memory headroom" in str(exc):
                row["status"] = "controlled_memory_block"
                rows.append(row)
                break
            raise exc
        row["status"] = "completed_standard_and_strict"
        report_path = a.output / a.case / (a.mode + ".json")
        report = json.loads(report_path.read_text())
        row["pid_stable"] = report["pid_stable"]
        row["png_hashes"] = [r["png_sha256"] for r in report["results"]]
        report_path.rename(
            report_path.with_name(a.mode + "_application_" + str(iteration) + ".json")
        )
        rows.append(row)
    ledger = {
        "application_constructed": True,
        "handler_groups": len(app.handlers),
        "before_models": state,
        "after_models": warmed_state,
        "canonical_components_loaded_and_warmed": canonical_state is not None,
        "canonical_residency": a.canonical_residency,
        "after_canonical_release": released_state,
        "retained_geometry_bytes": (
            0 if retained_geometry is None else retained_geometry.nbytes
        ),
        "cgroup_evidence": cgroup_evidence(),
        "after_canonical_components": canonical_state,
        "canonical_note": "component-residency plus baseline compositor; L renderer absent",
        "resident_extra_mib": a.resident_extra_mib,
        "after_resident_pressure": pressure_state,
        "rows": rows,
        "production_memory_qualified": False,
        "qualification": "real app and warmed PIPNet/MobileFace, no Telegram initialize or live request history",
    }
    (a.output / a.case / (a.mode + "_application_memory.json")).write_text(
        json.dumps(ledger, indent=2)
    )
    print("APPLICATION_MEMORY_RESULT", json.dumps(ledger), flush=True)
    assert app.handlers
    assert len(resident_pressure) == a.resident_extra_mib * 1024 * 1024


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--case", default="case01")
    p.add_argument("--mode", default="T_exact_field")
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--repetitions", type=int, default=3)
    p.add_argument("--resident-extra-mib", type=int, choices=[0, 64], default=0)
    p.add_argument("--canonical-assets", type=Path)
    p.add_argument(
        "--canonical-residency", choices=["resident", "scoped"], default="resident"
    )
    run(p.parse_args())
