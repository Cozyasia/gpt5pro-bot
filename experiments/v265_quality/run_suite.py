"""One reproducible command for the original procedural quality suite, not pilot admission."""

import json, subprocess, sys
from pathlib import Path
from .gate import qualify


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)

    def run(module, *args):
        subprocess.run([sys.executable, "-m", module, *map(str, args)], check=True)

    run("experiments.v265_quality.factory", out / "corpus", "--identities", "128")
    run("experiments.v265_quality.geometry_audit", out / "topology.json")
    for name, args in [
        ("mobile128", []),
        ("shuffle128", ["--backbone", "shufflenet_v2_x0_5"]),
        ("mobile256", ["--latent", "256"]),
        (
            "learned256",
            ["--latent", "256", "--representation", "learned", "--uv-size", "128"],
        ),
    ]:
        run(
            "experiments.v265_quality.train",
            out / "corpus",
            out / name,
            "--epochs",
            "12",
            *args
        )
    run("experiments.v265_quality.controlled", out / "corpus", out / "mobile128")
    stress = json.loads((out / "topology.json").read_text())
    report = json.loads((out / "mobile128/report.json").read_text())
    controlled = json.loads((out / "mobile128/controlled.json").read_text())
    gate = qualify(report, controlled, stress)
    cgroup = {}
    for name in ["memory.max", "memory.peak", "memory.events", "memory.swap.max"]:
        path = Path("/sys/fs/cgroup") / name
        cgroup[name] = path.read_text().strip() if path.exists() else None
    summary = dict(gate=gate, cgroup=cgroup, production_ready=False)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
