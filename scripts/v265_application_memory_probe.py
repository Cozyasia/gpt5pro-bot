"""Real application construction plus V265 worker, with network disabled.

Not a warmed live-daemon qualification: Telegram initialization, live request
history and other provider models are absent. Uses dummy credentials in CI.
"""

import argparse, json, os, socket, threading
from pathlib import Path


def deny_network(*args, **kwargs):
    raise RuntimeError("network forbidden in application memory probe")


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
        "rows": rows,
        "production_memory_qualified": False,
        "qualification": "real app and warmed PIPNet/MobileFace, no Telegram initialize or live request history",
    }
    (a.output / a.case / (a.mode + "_application_memory.json")).write_text(
        json.dumps(ledger, indent=2)
    )
    print("APPLICATION_MEMORY_RESULT", json.dumps(ledger), flush=True)
    assert app.handlers


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--case", default="case01")
    p.add_argument("--mode", default="T_exact_field")
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--repetitions", type=int, default=3)
    run(p.parse_args())
