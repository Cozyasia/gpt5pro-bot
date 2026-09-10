"""Mock records -> admission -> trainer -> export -> isolated worker -> cross-view."""

import argparse, json, os, subprocess, sys
from pathlib import Path
import numpy as np
from experiments.v265_prior.ingest import validate, sha, asset
from experiments.v265_prior.evaluate import cross_view_protocol
from experiments.v265_prior.benchmark import memory
from .mock import generate


def call(module, *args):
    subprocess.run(
        [sys.executable, "-m", module, *map(str, args)],
        check=True,
        env={**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"},
    )


def run(output, require_limit=False):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    cg = Path("/sys/fs/cgroup/memory.max")
    limit = cg.read_text().strip() if cg.exists() else None
    if require_limit and limit != "2147483648":
        raise ValueError(
            "actual isolated memory.max=2147483648 REQUIRED; not RLIMIT or shared host"
        )
    root = output / "dataset"
    model = output / "model"
    generated = generate(root)
    admission = validate(root, smoke=True)
    try:
        validate(root)
    except ValueError:
        commercial_reject = True
    else:
        raise AssertionError("mock entered commercial admission")
    call("experiments.v265_selfhost.trainer", root, model, "--smoke")
    manifest = json.loads((model / "model-manifest.json").read_text())
    rows = [json.loads(x) for x in (root / "manifest.jsonl").read_text().splitlines()]
    a = next(
        r
        for r in rows
        if r["split"] == "test" and r["expression_id"] == "1" and r["pose_id"] == "0"
    )
    b = next(
        r
        for r in rows
        if r["identity_id"] == a["identity_id"]
        and r["expression_id"] == "0"
        and r["pose_id"] == "1"
    )
    with np.load(asset(root, b["labels"]), allow_pickle=False) as z:
        labels = {k: z[k].copy() for k in z.files}
    with np.load(asset(root, b["ownership"]), allow_pickle=False) as z:
        ownership = {k: z[k].copy() for k in z.files}
    camera = json.loads(asset(root, b["camera"]).read_text())
    source = np.load(asset(root, a["rgb"]), allow_pickle=False)
    np.save(output / "source.npy", source)
    target = output / "target.npz"
    scene = np.load(asset(root, b["rgb"]), allow_pickle=False)
    np.savez(
        target,
        **camera_arrays(camera),
        expression=labels["expression"],
        scene=scene,
        **ownership
    )
    job = {
        "schema_version": 1,
        "job_id": "mock-withheld-source-smile-target-neutral",
        "source": {"path": "source.npy", "sha256": sha(output / "source.npy")},
        "target": {"path": "target.npz", "sha256": sha(target)},
        "model_manifest_sha256": sha(model / "model-manifest.json"),
    }
    (output / "job.json").write_text(json.dumps(job))
    call(
        "experiments.v265_selfhost.worker",
        output / "job.json",
        model,
        output / "worker",
        "--diagnostic",
    )
    call(
        "experiments.v265_selfhost.worker",
        output / "job.json",
        model,
        output / "repeat",
        "--diagnostic",
    )
    report = json.loads((output / "worker/result.json").read_text())
    repeat = json.loads((output / "repeat/result.json").read_text())
    if report["png_sha256"] != repeat["png_sha256"]:
        raise AssertionError("PNG nondeterminism")
    # Inference happened only from A. Saved canonical is projected into independently annotated B.
    canonical = np.load(output / "worker/canonical-identity.npz", allow_pickle=False)[
        "vertices"
    ]
    with np.load(asset(root, b["neutral_mesh"]), allow_pickle=False) as z:
        neutral = z["vertices"]
        tri = z["triangles"]
        basis = z["expression_basis"]
        regions = z["regions"]
    with np.load(asset(root, b["expression_mesh"]), allow_pickle=False) as z:
        withheld = z["vertices"]
    names = [
        "left_corner",
        "right_corner",
        "upper_outer",
        "upper_inner",
        "lower_outer",
        "lower_inner",
        "nose_base",
        "nose_left",
        "nose_right",
        "chin",
    ]
    ids = dict(zip(names, [345, 356, 323, 349, 401, 375, 271, 267, 276, 478]))
    inputs = dict(
        neutral_gt=neutral,
        expression_basis=basis,
        target_expression=labels["expression"],
        withheld_b=withheld,
        k=np.asarray(camera["K"]),
        r=np.asarray(camera["R"]),
        t=np.asarray(camera["t"]),
        triangles=tri,
        regions={
            name: np.where(regions == i)[0]
            for i, name in enumerate(
                ["jaw", "chin", "nose", "mouth", "eyes", "cheeks", "brows"]
            )
        },
        visible=np.ones(len(neutral), bool),
        boundary=np.arange(26),
        mouth_ids=ids,
    )
    evaluated = cross_view_protocol(
        lambda rgb: canonical,
        source,
        [
            {
                "pair_id": "mock-A-B",
                "split": "test",
                "source_identity_id": a["identity_id"],
                "target_identity_id": b["identity_id"],
                "source_image_sha256": a["rgb"]["sha256"],
                "target_image_sha256": b["rgb"]["sha256"],
                "evaluation_inputs": inputs,
            }
        ],
    )
    (output / "cross-view.json").write_text(json.dumps(evaluated, indent=2))
    summary = {
        "engineering_end_to_end": "PASS",
        "mock_only": True,
        "identity_quality_evidence": False,
        "commercial_training_allowed": False,
        "mock_commercial_admission_rejected": commercial_reject,
        "generated": generated,
        "admission": admission,
        "checkpoint_onnx": "PASS",
        "onnx_max_abs_errors": manifest["onnx_max_abs_errors"],
        "silhouette_gradient_l1": manifest["silhouette_to_encoder_gradient_l1"],
        "person_b_bit_exact": report["person_b_bit_exact"],
        "neck_bit_exact": report["neck_bit_exact"],
        "repeat_png_bit_exact": report["png_sha256"] == repeat["png_sha256"],
        "training_memory": manifest["training_memory"],
        "worker_memory": report["memory"],
        "actual_memory_limit": limit,
        "isolated_2gib_verified": require_limit and limit == "2147483648",
        "final_cgroup": memory(),
        "worker_latency_ms": report["total_ms"],
        "source_identity_hash": report["canonical_identity_sha256"],
        "machine_prequalified": False,
        "self_hosted_l2_mvp": False,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def camera_arrays(camera):
    return {key: np.asarray(camera[key], np.float32) for key in ["K", "R", "t"]}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("output")
    p.add_argument("--require-2gib", action="store_true")
    a = p.parse_args()
    print(json.dumps(run(a.output, a.require_2gib), indent=2))
