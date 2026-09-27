"""Standalone file-job worker. No vendor credentials, face API, or bot imports."""

import argparse, json, time
from pathlib import Path
import numpy as np
from PIL import Image
import onnxruntime as ort
from experiments.v265_prior.ingest import sha, asset, array_hash, require
from experiments.v265_prior.benchmark import memory
from .geometry import validate_geometry, raster, composite
from .gate import qualify

VERSION = "selfhost-worker-1"


def execute(job_path, model_dir, output, diagnostic=False):
    start = time.perf_counter()
    job_path = Path(job_path).resolve()
    root = job_path.parent
    job = json.loads(job_path.read_text())
    model_dir = Path(model_dir).resolve()
    require(
        set(job)
        == {"schema_version", "job_id", "source", "target", "model_manifest_sha256"},
        "unknown job keys; credentials/providers not supported",
    )
    require(
        job["schema_version"] == 1 and isinstance(job["job_id"], str) and job["job_id"],
        "invalid job",
    )
    manifest_path = model_dir / "model-manifest.json"
    require(
        sha(manifest_path) == job["model_manifest_sha256"], "model version mismatch"
    )
    manifest = json.loads(manifest_path.read_text())
    require(
        diagnostic
        or (not manifest["mock_only"] and manifest["commercial_training_allowed"]),
        "TEST ONLY weights denied outside diagnostic mode",
    )
    require(
        sha(model_dir / "identity.onnx") == manifest["onnx_sha256"],
        "ONNX hash mismatch",
    )
    require(
        sha(model_dir / "canonical.npz") == manifest["canonical_sha256"],
        "canonical hash mismatch",
    )
    source_path = asset(root, job["source"])
    target_path = asset(root, job["target"])
    if source_path.suffix == ".npy":
        source = np.load(source_path, allow_pickle=False)
    else:
        source = np.asarray(Image.open(source_path).convert("RGB"))
    require(
        source.dtype == np.uint8 and source.ndim == 3 and source.shape[2] == 3,
        "RGB source contract",
    )
    h, w = manifest["input_size"][2:]
    image = np.asarray(
        Image.fromarray(source).resize((w, h), Image.Resampling.BILINEAR)
    ).copy()
    tensor = image.transpose(2, 0, 1)[None].astype("float32") / 255
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    init = time.perf_counter()
    session = ort.InferenceSession(
        str(model_dir / "identity.onnx"),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    init_ms = (time.perf_counter() - init) * 1000
    infer = time.perf_counter()
    identity, residual, canonical, albedo, semantic = session.run(None, {"rgb": tensor})
    infer_ms = (time.perf_counter() - infer) * 1000
    # Re-run same source to test warmed deterministic execution without any B image.
    warm = time.perf_counter()
    second = session.run(None, {"rgb": tensor})
    warm_ms = (time.perf_counter() - warm) * 1000
    require(
        all(
            np.array_equal(a, b)
            for a, b in zip([identity, residual, canonical, albedo, semantic], second)
        ),
        "nondeterministic inference",
    )
    snapshots = {"after_inference": memory()}
    with np.load(model_dir / "canonical.npz", allow_pickle=False) as z:
        base = {k: z[k].copy() for k in z.files}
    with np.load(target_path, allow_pickle=False) as z:
        target = {k: z[k].copy() for k in z.files}
    for key in [
        "K",
        "R",
        "t",
        "expression",
        "scene",
        "support",
        "protected",
        "neck",
        "occlusion",
    ]:
        require(key in target, "missing target " + key)
    require(
        target["R"].shape == (3, 3)
        and np.allclose(target["R"].T @ target["R"], np.eye(3), atol=1e-5)
        and np.isclose(np.linalg.det(target["R"]), 1, atol=1e-5),
        "invalid rotation",
    )
    source_hash = array_hash(canonical[0])
    expression = np.einsum("e,enc->nc", target["expression"], base["expression_basis"])
    cfg = manifest["training_config"]
    geometry = validate_geometry(
        canonical[0] + expression,
        base["neutral"] + expression,
        base["triangles"],
        cfg["geometry_area_bounds"],
        cfg["geometry_edge_bounds"],
    )
    size = target["scene"].shape[0]
    require(
        target["scene"].shape == (size, size, 3), "square target scene required by v1"
    )
    for key in ["support", "protected", "neck", "occlusion"]:
        require(
            target[key].shape == (size, size) and target[key].dtype == np.bool_,
            "invalid ownership mask",
        )
    result = raster(
        canonical[0] + expression,
        base["triangles"],
        target["K"],
        target["R"],
        target["t"],
        size,
        base["uv"],
        albedo[0].transpose(1, 2, 0),
        illumination=target.get("illumination", np.array([1.0, 0, 0])),
    )
    final = composite(
        target["scene"],
        result,
        target["support"],
        target["protected"],
        target["neck"],
        target["occlusion"],
    )
    require(
        array_hash(canonical[0]) == source_hash,
        "target contaminated canonical identity",
    )
    critical = (
        target["support"]
        & ~target["protected"]
        & ~target["neck"]
        & ~target["occlusion"]
    )
    holes = int(np.count_nonzero(critical & ~result["visibility"]))
    gate = qualify(
        {"geometry_validity": True, "visibility_complete": holes == 0}, manifest
    )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    Image.fromarray(final).save(output / "candidate.png", format="PNG")
    np.savez(
        output / "canonical-identity.npz",
        vertices=canonical[0],
        identity=identity[0],
        residual=residual[0],
    )
    np.save(output / "source-semantic-logits.npy", semantic[0])
    report = {
        "job_id": job["job_id"],
        "worker_version": VERSION,
        "source_sha256": job["source"]["sha256"],
        "model_manifest_sha256": job["model_manifest_sha256"],
        "canonical_identity_sha256": source_hash,
        "target_sha256": job["target"]["sha256"],
        "renderer_version": manifest["renderer_version"],
        "config_sha256": manifest["config_sha256"],
        "geometry": geometry,
        "raster": result["diagnostics"],
        "critical_holes": holes,
        "quality_gate": gate,
        "person_b_bit_exact": bool(
            np.array_equal(
                final[target["protected"]], target["scene"][target["protected"]]
            )
        ),
        "neck_bit_exact": bool(
            np.array_equal(final[target["neck"]], target["scene"][target["neck"]])
        ),
        "deterministic_inference": True,
        "cold_session_ms": init_ms,
        "first_inference_ms": infer_ms,
        "warm_inference_ms": warm_ms,
        "total_ms": (time.perf_counter() - start) * 1000,
        "memory": {**snapshots, "after_render": memory()},
        "png_sha256": sha(output / "candidate.png"),
        "diagnostic_only": diagnostic,
    }
    (output / "result.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("job")
    p.add_argument("model")
    p.add_argument("output")
    p.add_argument("--diagnostic", action="store_true")
    a = p.parse_args()
    r = execute(a.job, a.model, a.output, a.diagnostic)
    print(
        json.dumps(
            {
                "job_id": r["job_id"],
                "quality_gate": r["quality_gate"],
                "total_ms": r["total_ms"],
            }
        )
    )
