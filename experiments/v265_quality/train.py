"""Bounded synthetic quality experiment; test identities never train or select weights."""

import argparse, hashlib, json, resource, time, os, subprocess
from pathlib import Path
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from experiments.v265_prior.model import IdentityEncoder
from experiments.v265_prior.evaluate import topology_metrics
from experiments.v265_quality.factory import REGIONS, VERSION


class Model(nn.Module):
    def __init__(self, s, backbone, latent, representation, uv_size=64):
        super().__init__()
        self.encoder = IdentityEncoder(backbone, latent, 12)
        self.coeff = nn.Linear(latent, 24)
        self.representation = representation
        self.register_buffer(
            "expression_q",
            torch.linalg.qr(torch.tensor(s["expression"]).reshape(8, -1).T).Q,
        )
        for name in ["neutral", "basis", "residual"]:
            self.register_buffer(name, torch.tensor(s[name]))
        self.dense = (
            nn.Sequential(
                nn.Linear(latent, 64), nn.SiLU(), nn.Linear(64, len(s["neutral"]) * 3)
            )
            if representation == "learned"
            else None
        )
        if self.dense is not None:
            nn.init.zeros_(self.dense[-1].weight)
            nn.init.zeros_(self.dense[-1].bias)
        self.albedo_seed = nn.Linear(latent, 32 * 4 * 4)
        layers = []
        channels = 32
        size = 4
        while size < uv_size:
            layers.extend([nn.ConvTranspose2d(channels, 16, 4, 2, 1), nn.SiLU()])
            channels = 16
            size *= 2
        self.albedo_head = nn.Sequential(*layers, nn.Conv2d(16, 3, 1), nn.Sigmoid())
        self.parsing = nn.Sequential(
            nn.Conv2d(3, 16, 3, padding=1),
            nn.SiLU(),
            nn.Conv2d(16, 16, 3, padding=1, groups=16),
            nn.SiLU(),
            nn.Conv2d(16, 15, 1),
        )

    def forward(self, x):
        code, r = self.encoder(x)
        c = torch.tanh(self.coeff(code))
        v = (
            self.neutral
            + torch.einsum("bk,knc->bnc", c, self.basis)
            + torch.einsum("bk,knc->bnc", r, self.residual)
        )
        if self.dense is not None:
            raw = 0.001 * torch.tanh(self.dense(code))
            raw = raw - (raw @ self.expression_q) @ self.expression_q.T
            # Orthogonalization can increase point magnitude: apply a global bound.
            scale = 0.001 / raw.abs().amax(1, keepdim=True).clamp_min(0.001)
            v = v + (raw * scale).reshape(-1, len(self.neutral), 3)
        return (
            v,
            c,
            self.albedo_head(self.albedo_seed(code).reshape(-1, 32, 4, 4)),
            self.parsing(x),
        )


def load(root):
    rows = [json.loads(l) for l in (root / "manifest.jsonl").read_text().splitlines()]
    seen = {}
    assets = []
    for row in rows:
        path = root / row["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("checksum")
        if row["identity"] in seen and seen[row["identity"]] != row["split"]:
            raise ValueError("identity leakage")
        seen[row["identity"]] = row["split"]
        with np.load(path) as a:
            assets.append(
                {
                    k: a[k]
                    for k in [
                        "rgb",
                        "neutral",
                        "coefficients",
                        "albedo",
                        "semantic",
                        "expression",
                        "K",
                        "R",
                        "t",
                    ]
                }
            )
    data = {k: torch.tensor(np.stack([a[k] for a in assets])) for k in assets[0]}
    data["rgb"] = data["rgb"].permute(0, 3, 1, 2)
    data["albedo"] = data["albedo"].permute(0, 3, 1, 2)
    return rows, data


def evaluate(model, rows, data, split, s):
    model.eval()
    ids = [i for i, r in enumerate(rows) if r["split"] == split]
    errors = []
    base = []
    regional = {k: [] for k in REGIONS}
    predictions = {}
    albedo = []
    coeff = []
    orient = 0
    area = [float("inf"), 0]
    edge = [float("inf"), 0]
    confusion = np.zeros((15, 15), np.int64)
    with torch.no_grad():
        for i in ids:
            v, c, a, p = model(data["rgb"][i : i + 1])
            v = v[0].cpu().numpy()
            gt = data["neutral"][i].numpy()
            error = np.linalg.norm(v - gt, axis=1) * 1000
            errors.append(float(np.sqrt(np.mean(error**2))))
            base.append(
                float(np.sqrt(np.mean(np.sum((s["neutral"] - gt) ** 2, axis=1))) * 1000)
            )
            for k, name in enumerate(REGIONS):
                regional[name].append(
                    float(np.sqrt(np.mean(error[s["regions"] == k] ** 2)))
                )
            predictions.setdefault(rows[i]["identity"], []).append(v)
            albedo.append(
                float(
                    F.mse_loss(
                        a,
                        F.interpolate(
                            data["albedo"][i : i + 1],
                            size=a.shape[-2:],
                            mode="bilinear",
                            align_corners=False,
                        ),
                    )
                )
            )
            coeff.append(float(F.mse_loss(c, data["coefficients"][i : i + 1])))
            metrics = topology_metrics(v, s["neutral"], s["triangles"])
            orient += metrics["orientation_failures"]
            area = [
                min(area[0], metrics["local_area_ratio"]["min"]),
                max(area[1], metrics["local_area_ratio"]["max"]),
            ]
            edge = [
                min(edge[0], metrics["edge_stretch"]["min"]),
                max(edge[1], metrics["edge_stretch"]["max"]),
            ]
            truth = data["semantic"][i].numpy().ravel()
            prediction = p.argmax(1)[0].numpy().ravel()
            confusion += np.bincount(truth * 15 + prediction, minlength=225).reshape(
                15, 15
            )
    drift = [
        float(np.sqrt(np.mean(np.sum((np.stack(v) - v[0]) ** 2, axis=-1))) * 1000)
        for v in predictions.values()
    ]
    union = confusion.sum(0) + confusion.sum(1) - confusion.diagonal()
    iou = np.divide(confusion.diagonal(), union, out=np.zeros(15), where=union > 0)
    return dict(
        identities=len(predictions),
        records=len(ids),
        geometry_rmse_mm=float(np.mean(errors)),
        mean_prior_rmse_mm=float(np.mean(base)),
        relative_to_mean=float(np.mean(errors) / np.mean(base)),
        regional_rmse_mm={k: float(np.mean(v)) for k, v in regional.items()},
        combined_pose_expression_light_accessory_drift_mm=float(np.mean(drift)),
        coefficient_mse=float(np.mean(coeff)),
        albedo_mse=float(np.mean(albedo)),
        parsing_iou=iou.tolist(),
        parsing_present_classes=np.where(union > 0)[0].tolist(),
        orientation_failures=int(orient),
        area_ratio=area,
        edge_stretch=edge,
        source_inference_only=True,
        expression_annotation_independent=True,
        case06_full_surface_acceptance=False,
        case08_intrinsic_acceptance=False,
    )


def run(
    root,
    out,
    backbone="mobilenet_v3_small",
    latent=128,
    representation="parametric",
    epochs=12,
    uv_size=64,
    device="cpu",
):
    torch.set_num_threads(2)
    torch.manual_seed(265)
    np.random.seed(265)
    torch.use_deterministic_algorithms(True)
    root, out = Path(root), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rows, data = load(root)
    s = dict(np.load(root / "topology.npz"))
    m = Model(s, backbone, latent, representation, uv_size)
    m = m.to(device)
    data = {k: v.to(device) for k, v in data.items()}
    optimizer = torch.optim.AdamW(m.parameters(), lr=0.002)
    train = [i for i, r in enumerate(rows) if r["split"] == "train"]
    rng = np.random.default_rng(265)
    # Fixed finite budget; validation selects checkpoint; sealed test is evaluated once.
    losses = []
    best = float("inf")
    start = time.monotonic()
    for epoch in range(epochs):
        m.train()
        epochloss = []
        for batch in np.array_split(
            rng.permutation(train), int(np.ceil(len(train) / 16))
        ):
            idx = torch.tensor(batch)
            v, c, a, p = m(data["rgb"][idx])
            gt = data["neutral"][idx]
            pair = torch.tensor([train[(train.index(int(i)) // 8) * 8] for i in batch])
            vp, _, _, _ = m(data["rgb"][pair])
            geo = F.mse_loss(v * 1000, gt * 1000)
            co = F.mse_loss(c, data["coefficients"][idx])
            consistency = F.mse_loss(v * 1000, vp * 1000)
            at = F.interpolate(
                data["albedo"][idx],
                size=(uv_size, uv_size),
                mode="bilinear",
                align_corners=False,
            )
            appearance = F.mse_loss(a, at)
            parse = F.cross_entropy(p, data["semantic"][idx].long())
            # Orientation and edge metric penalties are evaluated on all native triangles.
            tri = torch.tensor(s["triangles"], device=device).long()
            pv = v[:, tri]
            rv = m.neutral[tri]
            pn = torch.cross(
                pv[:, :, 1] - pv[:, :, 0], pv[:, :, 2] - pv[:, :, 0], dim=-1
            )
            rn = torch.cross(rv[:, 1] - rv[:, 0], rv[:, 2] - rv[:, 0], dim=-1)
            dot = (pn * rn).sum(-1) / (rn.square().sum(-1) + 1e-16)
            barrier = F.relu(0.3 - dot).square().mean()
            loss = (
                geo
                + 0.2 * co
                + 0.2 * consistency
                + 0.2 * appearance
                + 0.02 * parse
                + barrier
            )
            if not torch.isfinite(loss):
                raise RuntimeError("nonfinite loss")
            optimizer.zero_grad()
            loss.backward()
            if any(
                p.grad is not None and not torch.isfinite(p.grad).all()
                for p in m.parameters()
            ):
                raise RuntimeError("nonfinite gradient")
            torch.nn.utils.clip_grad_norm_(m.parameters(), 10)
            optimizer.step()
            epochloss.append(float(loss.detach()))
        # select by independent identity geometry, not training loss
        m.eval()
        val = []
        with torch.no_grad():
            for i, r in enumerate(rows):
                if r["split"] == "validation":
                    val.append(
                        float(
                            F.mse_loss(
                                m(data["rgb"][i : i + 1])[0], data["neutral"][i : i + 1]
                            )
                        )
                    )
        score = float(np.mean(val))
        losses.append(
            dict(epoch=epoch, loss=float(np.mean(epochloss)), validation_mse=score)
        )
        print(json.dumps(losses[-1]), flush=True)
        if score < best:
            best = score
            torch.save(m.state_dict(), out / "weights.pt")
    m.load_state_dict(
        torch.load(out / "weights.pt", weights_only=True, map_location=device)
    )
    m = m.cpu()
    data = {k: v.cpu() for k, v in data.items()}
    m.eval()
    report = evaluate(m, rows, data, "test", s)
    x = data["rgb"][:1]
    with torch.no_grad():
        before = m(x)
        repeat = m(x)
        deterministic = all(torch.equal(a, b) for a, b in zip(before, repeat))
        tick = time.monotonic()
        for _ in range(30):
            m(x)
        latency = (time.monotonic() - tick) / 30 * 1000
    onnx = out / "model.onnx"
    torch.onnx.export(
        m,
        x,
        onnx,
        input_names=["rgb"],
        output_names=["canonical", "coefficients", "albedo", "parsing"],
        opset_version=17,
    )
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    session = ort.InferenceSession(str(onnx), opts, providers=["CPUExecutionProvider"])
    native = [z.detach().numpy() for z in before]
    exported = session.run(None, {"rgb": x.numpy()})
    parity = max(float(np.max(np.abs(a - b))) for a, b in zip(native, exported))
    report.update(
        training_device=device,
        cuda_peak_bytes=(
            torch.cuda.max_memory_allocated() if device.startswith("cuda") else None
        ),
        code_commit=os.environ.get("V265_CODE_COMMIT")
        or subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        source_hashes={
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(__file__).parent.glob("*.py")
        },
        backbone=backbone,
        latent=latent,
        representation=representation,
        uv_size=uv_size,
        epochs=epochs,
        training_seconds=time.monotonic() - start,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        latency_ms=latency,
        model_bytes=sum(p.numel() * p.element_size() for p in m.parameters()),
        deterministic=deterministic,
        onnx_max_abs_error=parity,
        onnx_sha256=hashlib.sha256(onnx.read_bytes()).hexdigest(),
        dataset_manifest_sha256=hashlib.sha256(
            (root / "manifest.jsonl").read_bytes()
        ).hexdigest(),
        generator=VERSION,
        history=losses,
        v0=False,
        real_human_quality_proven=False,
        weights_sha256=hashlib.sha256((out / "weights.pt").read_bytes()).hexdigest(),
        loss_weights=dict(
            geometry=1,
            coefficients=0.2,
            crossview=0.2,
            appearance=0.2,
            parsing=0.02,
            orientation=1,
        ),
    )
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "history"}, indent=2))
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("root")
    p.add_argument("out")
    p.add_argument("--backbone", default="mobilenet_v3_small")
    p.add_argument("--latent", type=int, default=128)
    p.add_argument(
        "--representation", default="parametric", choices=["parametric", "learned"]
    )
    p.add_argument("--epochs", type=int, default=12)
    p.add_argument("--uv-size", type=int, default=64)
    p.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    a = p.parse_args()
    run(**vars(a))
