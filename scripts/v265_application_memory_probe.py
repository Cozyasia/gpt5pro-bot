"""Real application construction plus V265 worker, with network disabled.

Not a warmed live-daemon qualification: Telegram initialization, live request
history and other provider models are absent. Uses dummy credentials in CI.
"""

import argparse, json, os, socket, threading
from pathlib import Path


def deny_network(*args, **kwargs):
    raise RuntimeError("network forbidden in application memory probe")


def run(a):
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
    a.sampler = MemorySampler()
    a.sampler.thread.start()
    errors = []

    def task():
        try:
            worker(a)
        except BaseException as exc:
            errors.append(exc)
        finally:
            a.sampler.stop.set()

    thread = threading.Thread(target=task, daemon=True)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    report_path = a.output / a.case / (a.mode + ".json")
    report = json.loads(report_path.read_text())
    report["application_constructed"] = True
    report["application_baseline_memory_state"] = state
    report["qualification"] = (
        "constructed real application; no Telegram initialize or warmed live request history"
    )
    report_path.write_text(json.dumps(report, indent=2))
    # Keep the complete application object resident throughout both passes.
    assert app.handlers


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--case", default="case01")
    p.add_argument("--mode", default="T_exact_field")
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args())
