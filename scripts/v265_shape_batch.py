"""Isolated offline geometry ablations. A folded field is a recorded rejection.

Unexpected worker errors fail the job; a geometric rejection is never counted
as a produced, accepted, or passing image. This is an experiment execution CI.
"""

import argparse, json, subprocess, sys
from pathlib import Path


def run(a):
    ledger = []
    for mode in a.modes or (
        "A_baseline",
        "D_mask_core",
        "T_exact_field",
        "F_jaw_shape",
        "G_face_shape",
        "H_jaw_silhouette",
        "I_ortho_jaw",
        "J_ortho_face",
        "K_ortho_silhouette",
    ):
        log = a.output / a.case / (mode + ".log")
        command = [
            sys.executable,
            "-m",
            "scripts.v265_transfer_matrix",
            "--worker",
            "--daemon",
            "--case",
            a.case,
            "--mode",
            mode,
            "--models",
            str(a.models),
            "--output",
            str(a.output),
        ]
        with log.open("w") as stream:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
        row = {"case": a.case, "mode": mode, "exit_code": result.returncode}
        if result.returncode:
            if (
                log.read_text()
                .rstrip()
                .endswith("ValueError: folded inverse geometry field")
            ):
                row["status"] = "geometry_rejected"
                row["image_produced"] = False
            else:
                raise RuntimeError("unexpected worker failure: " + str(log))
        else:
            report = json.loads((a.output / a.case / (mode + ".json")).read_text())
            row.update(
                status="produced_not_approved",
                image_produced=True,
                peak_rss_kib=report["peak_rss_kib"],
            )
        ledger.append(row)
        print("SHAPE_EXPERIMENT", json.dumps(row), flush=True)
    (a.output / a.case / "shape-ledger.json").write_text(
        json.dumps({"rows": ledger, "production_accepted": False}, indent=2)
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--case", required=True)
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--modes", nargs="+", help="Explicit bounded ablation subset")
    run(p.parse_args())
