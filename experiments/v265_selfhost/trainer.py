"""Complete real-record supervision, validation, checkpoint and ONNX export chain."""

import argparse, json, hashlib, subprocess, time, os
from pathlib import Path
import numpy as np
import torch
from .data import Records, prepare
from .model import Heads, decoder_from_npz, validity_losses
from .geometry import project_torch, soft_surface
from experiments.v265_prior.ingest import sha
from experiments.v265_prior.benchmark import memory

LOSS_NAMES = [
    "neutral",
    "coefficients",
    "residual",
    "paired_identity",
    "expression_orthogonality",
    "silhouette",
    "visibility",
    "landmarks",
    "depth",
    "jaw",
    "chin",
    "nose",
    "mouth",
    "eyes",
    "cheeks",
    "brows",
    "orientation",
    "area",
    "edge",
    "laplacian",
    "arap_like",
    "orientation_barrier",
    "compression",
    "expansion",
    "residual_bound",
    "albedo",
    "parsing",
]


def configuration():
    return {
        "seed": 265,
        "backbone": "mobilenet_v3_small",
        "identity_dim": 192,
        "residual_dim": 32,
        "uv_size": 16,
        "learning_rate": 1e-4,
        "epochs": 1,
        "loss_weights": {name: 1.0 for name in LOSS_NAMES},
        "gradient_clip": 1.0,
        "geometry_area_bounds": [0.25, 4.0],
        "geometry_edge_bounds": [0.5, 2.0],
        "curriculum_stage": "ENGINEERING_ALL_LOSSES",
        "quality_exit_thresholds": None,
    }


def batch(record):
    return {
        k: torch.from_numpy(v).unsqueeze(0) if isinstance(v, np.ndarray) else v
        for k, v in record.items()
    }


def supervise(model, decoder, b, regions):
    identity, residual, albedo, semantic = model(b["rgb"])
    paired, _ = model.identity(b["paired_rgb"])
    canonical = decoder(identity, residual)
    displacement = torch.einsum(
        "be,enc->bnc", b["expression"], decoder.expression_basis
    )
    expressed = canonical + displacement
    reference = b["neutral"] + displacement
    xy, z = project_torch(expressed, b["K"], b["R"], b["t"])
    points = (
        xy[:, decoder.triangles[decoder.correspondence_ids]]
        * decoder.correspondence_weights[None, :, :, None]
    ).sum(2)
    size = b["rgb"].shape[-1]
    coverage, depth = soft_surface(
        expressed, decoder.triangles, b["K"], b["R"], b["t"], size
    )
    delta = torch.einsum("bk,knc->bnc", residual, decoder.residual_basis)
    target_delta = torch.einsum(
        "bk,knc->bnc", b["residual_coefficients"], decoder.residual_basis
    )
    mse = lambda a, b: (a - b).square().mean()
    valid = b["visibility"].bool()
    lmvis = b["landmark_visibility"].bool()
    if not valid.any() or not lmvis.any():
        raise ValueError("missing visible supervision")
    losses = validity_losses(expressed, reference, decoder.triangles, delta)
    losses.update(
        neutral=mse(canonical, b["neutral"]),
        coefficients=mse(identity, b["coefficients"]),
        residual=mse(delta, target_delta),
        paired_identity=mse(identity, paired),
        expression_orthogonality=(delta.flatten(1) @ decoder.expression_q)
        .square()
        .mean(),
        silhouette=torch.nn.functional.binary_cross_entropy(
            coverage.clamp(1e-6, 1 - 1e-6), valid.float()
        ),
        visibility=mse(coverage, valid.float()),
        landmarks=mse(points[lmvis] / size, b["landmarks"][..., :2][lmvis] / size),
        depth=mse(depth[valid], b["depth"][valid]),
        albedo=mse(albedo, b["albedo"]),
        parsing=torch.nn.functional.cross_entropy(semantic, b["semantic"].long()),
    )
    for i, name in enumerate(
        ["jaw", "chin", "nose", "mouth", "eyes", "cheeks", "brows"]
    ):
        mask = regions == i
        if not mask.any():
            raise ValueError("missing critical region " + name)
        losses[name] = mse(canonical[:, mask], b["neutral"][:, mask])
    return losses, canonical


class Export(torch.nn.Module):
    def __init__(self, model, decoder):
        super().__init__()
        self.model = model
        self.decoder = decoder

    def forward(self, rgb):
        i, r, a, s = self.model(rgb)
        return i, r, self.decoder(i, r), a, s


def run(root, output, smoke=False, config=None, resume=None):
    config = configuration() if config is None else config
    if set(config["loss_weights"]) != set(LOSS_NAMES):
        raise ValueError("explicit weight required for EVERY loss")
    if not all(np.isfinite(w) and w >= 0 for w in config["loss_weights"].values()):
        raise ValueError("invalid loss weights")
    if not smoke and config["curriculum_stage"] == "ENGINEERING_ALL_LOSSES":
        raise ValueError("commercial training requires explicit curriculum stage")
    from .curriculum import weights_for

    expected = weights_for(config["curriculum_stage"], LOSS_NAMES)
    if any(
        config["loss_weights"][name] != 0 for name in LOSS_NAMES if expected[name] == 0
    ):
        raise ValueError("loss active before curriculum stage")
    torch.set_num_threads(1)
    torch.manual_seed(config["seed"])
    np.random.seed(config["seed"])
    torch.use_deterministic_algorithms(True)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    basis = output / "canonical.npz"
    provenance = prepare(root, basis, smoke=smoke)
    train = Records(root, "train", basis, smoke)
    val = Records(root, "validation", basis, smoke)
    model = Heads(config["backbone"])
    decoder = decoder_from_npz(basis)
    regions = torch.from_numpy(np.load(basis)["regions"])
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"])
    if resume:
        checkpoint = torch.load(resume, map_location="cpu", weights_only=True)
        if checkpoint["dataset_sha256"] != train.admission["manifest_sha256"]:
            raise ValueError("resume dataset mismatch")
        if checkpoint["config"] != config:
            raise ValueError("resume config mismatch")
        model.load_state_dict(checkpoint["model"])
        optimizer.load_state_dict(checkpoint["optimizer"])
    history = []
    start = time.perf_counter()
    gradient_evidence = []
    for epoch in range(config["epochs"]):
        # Sequential deterministic order is intentional for this pilot baseline.
        model.train()
        model.identity.features.eval()  # batch1 frozen BN statistics; explicit pilot policy
        train_metrics = []
        for index in range(len(train)):
            b = batch(train[index])
            optimizer.zero_grad(set_to_none=True)
            losses, canonical = supervise(model, decoder, b, regions)
            total = sum(losses[k] * config["loss_weights"][k] for k in LOSS_NAMES)
            if not torch.isfinite(total):
                raise ValueError("nonfinite loss")
            total.backward()
            if any(
                p.grad is not None and not torch.isfinite(p.grad).all()
                for p in model.parameters()
            ):
                raise ValueError("nonfinite gradient")
            torch.nn.utils.clip_grad_norm_(model.parameters(), config["gradient_clip"])
            optimizer.step()
            train_metrics.append({k: float(v.detach()) for k, v in losses.items()})
        model.eval()
        validation = []
        with torch.no_grad():
            for index in range(len(val)):
                losses, _ = supervise(model, decoder, batch(val[index]), regions)
                validation.append({k: float(v) for k, v in losses.items()})
        history.append(
            {
                "epoch": epoch,
                "train": {
                    k: float(np.mean([x[k] for x in train_metrics])) for k in LOSS_NAMES
                },
                "validation": {
                    k: float(np.mean([x[k] for x in validation])) for k in LOSS_NAMES
                },
            }
        )
    training_memory = memory()
    # Verify actual final silhouette gradients reach identity encoder, independent of neutral loss.
    model.eval()
    model.zero_grad(set_to_none=True)
    losses, _ = supervise(model, decoder, batch(train[0]), regions)
    losses["silhouette"].backward()
    gradient = sum(
        float(p.grad.abs().sum())
        for p in model.identity.parameters()
        if p.grad is not None
    )
    if not np.isfinite(gradient) or gradient <= 0:
        raise ValueError("silhouette-to-encoder gradient broken")
    checkpoint = dict(
        model=model.state_dict(),
        optimizer=optimizer.state_dict(),
        config=config,
        dataset_sha256=train.admission["manifest_sha256"],
        commercial_training_allowed=not smoke,
    )
    torch.save(checkpoint, output / "checkpoint.pt")
    # Strict load before export, using weights_only. Test-only provenance survives serialization.
    restored = torch.load(
        output / "checkpoint.pt", map_location="cpu", weights_only=True
    )
    model.load_state_dict(restored["model"])
    wrapper = Export(model, decoder).eval()
    example = batch(train[0])["rgb"]
    with torch.no_grad():
        expected = [x.numpy() for x in wrapper(example)]
    onnx = output / "identity.onnx"
    torch.onnx.export(
        wrapper,
        example,
        str(onnx),
        opset_version=17,
        input_names=["rgb"],
        output_names=["identity", "residual", "canonical", "albedo", "semantic"],
        dynamic_axes={"rgb": {0: "batch"}},
    )
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(onnx), sess_options=options, providers=["CPUExecutionProvider"]
    )
    actual = session.run(None, {"rgb": example.numpy()})
    errors = [float(np.max(np.abs(a - b))) for a, b in zip(actual, expected)]
    if max(errors) > 1e-4:
        raise ValueError("ONNX/native mismatch " + str(errors))
    source_hash = hashlib.sha256(
        b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))
    ).hexdigest()
    revision = (
        os.environ.get("V265_CODE_COMMIT")
        or subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    )
    manifest = {
        "schema_version": 1,
        "architecture": config["backbone"],
        "code_commit": revision,
        "source_code_sha256": source_hash,
        "dataset_manifest_sha256": train.admission["manifest_sha256"],
        "rights_ledger_sha256": train.admission["rights_sha256"],
        "training_config": config,
        "config_sha256": hashlib.sha256(
            json.dumps(config, sort_keys=True).encode()
        ).hexdigest(),
        "random_seed": config["seed"],
        "parent_checkpoint_sha256": sha(resume) if resume else None,
        "onnx_sha256": sha(onnx),
        "canonical_sha256": sha(basis),
        "checkpoint_sha256": sha(output / "checkpoint.pt"),
        "topology_version": train.rows[0]["topology_version"],
        "expression_basis_version": "train-source-expression-v1",
        "parsing_version": "own-depthwise15-v1",
        "renderer_version": "v265-local-geometry-1",
        "input_size": list(example.shape),
        "commercial_training_allowed": not smoke,
        "identity_quality_qualified": False,
        "mock_only": smoke,
        "silhouette_to_encoder_gradient_l1": gradient,
        "onnx_max_abs_errors": errors,
        "training_memory": training_memory,
        "total_seconds": time.perf_counter() - start,
        "history": history,
        "basis_provenance": provenance,
        "curriculum_exit_pass": False,
        "stages_completed_for_quality": [],
    }
    (output / "model-manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("root")
    p.add_argument("output")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--config")
    p.add_argument("--resume")
    a = p.parse_args()
    config = json.loads(Path(a.config).read_text()) if a.config else None
    r = run(a.root, a.output, a.smoke, config, a.resume)
    print(
        json.dumps(
            {
                k: r[k]
                for k in [
                    "total_seconds",
                    "onnx_max_abs_errors",
                    "silhouette_to_encoder_gradient_l1",
                    "training_memory",
                ]
            },
            indent=2,
        )
    )
