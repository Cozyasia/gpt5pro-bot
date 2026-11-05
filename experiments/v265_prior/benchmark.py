"""Fresh-process engineering benchmark; random weights/images, no identity claims."""

import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


def memory():
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    cgroup = {}
    for name in ["memory.current", "memory.max", "memory.peak", "memory.stat"]:
        p = Path("/sys/fs/cgroup") / name
        if p.exists():
            text = p.read_text().strip()
            if name == "memory.stat":
                cgroup["cache_bytes"] = {
                    k: int(v)
                    for k, v in (s.split() for s in text.splitlines())
                    if k in ["file", "inactive_file", "slab_reclaimable"]
                }
            else:
                cgroup[name] = text
    return {
        "rss_kib": int(status["VmRSS"].split()[0]),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "shared_host_cgroup": cgroup,
    }


def worker(mode, backbone, directory):
    import numpy as np

    start = time.perf_counter()
    result = {"mode": mode, "backbone": backbone, "quality_evidence": False}
    x = np.random.default_rng(265).normal(size=(1, 3, 224, 224)).astype("float32")
    path = Path(directory) / f"{backbone}.onnx"
    if mode in ["native", "export", "train_smoke"]:
        import torch
        from .model import IdentityEncoder

        torch.set_num_threads(1)
        torch.manual_seed(265)
        result["framework_only"] = memory()
        m = IdentityEncoder(backbone).eval()
        result["parameters"] = sum(p.numel() for p in m.parameters())
        result["model_bytes"] = sum(
            p.numel() * p.element_size() for p in m.parameters()
        )
        inp = torch.from_numpy(x)
        if mode == "train_smoke":
            m.train()
            optim = torch.optim.AdamW(m.parameters(), lr=1e-4)
            inp = inp.repeat(2, 1, 1, 1)
            losses = []
            for _ in range(2):
                optim.zero_grad()
                a, b = m(inp)
                loss = a.square().mean() + b.square().mean()
                loss.backward()
                assert all(
                    p.grad is None or torch.isfinite(p.grad).all()
                    for p in m.parameters()
                )
                optim.step()
                losses.append(float(loss.detach()))
            result.update(
                finite_gradients=True, steps=2, smoke_losses=losses, memory=memory()
            )
            return result
        if mode == "export":
            with torch.no_grad():
                expected = m(inp)
            np.savez(
                Path(directory) / f"{backbone}-expected.npz",
                identity=expected[0].numpy(),
                residual=expected[1].numpy(),
            )
            torch.onnx.export(
                m,
                inp,
                str(path),
                input_names=["rgb"],
                output_names=["identity", "residual"],
                dynamic_axes={
                    "rgb": {0: "batch"},
                    "identity": {0: "batch"},
                    "residual": {0: "batch"},
                },
                opset_version=17,
            )
            result.update(onnx_bytes=path.stat().st_size, memory=memory())
            return result

        def run():
            with torch.inference_mode():
                return m(inp)

    elif mode == "onnx":
        import onnxruntime as ort

        result["framework_only"] = memory()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(
            str(path), sess_options=options, providers=["CPUExecutionProvider"]
        )

        def run():
            return session.run(None, {"rgb": x})

        expected = np.load(Path(directory) / f"{backbone}-expected.npz")
        actual = run()
        errors = [
            float(np.max(np.abs(a - expected[k])))
            for a, k in zip(actual, ["identity", "residual"])
        ]
        assert max(errors) < 1e-5
        result["export_max_abs_error"] = errors
        result["onnx_bytes"] = path.stat().st_size
    else:
        raise ValueError(mode)
    result["initialization_ms"] = (time.perf_counter() - start) * 1000
    for _ in range(5):
        run()
    result["warmed"] = memory()
    times = []
    for _ in range(30):
        t = time.perf_counter()
        out = run()
        times.append((time.perf_counter() - t) * 1000)
    result.update(
        latency_ms={
            "p50": float(np.median(times)),
            "p95": float(np.quantile(times, 0.95)),
        },
        output_shapes=[list(v.shape) for v in out],
        memory=memory(),
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--worker", choices=["native", "export", "onnx", "train_smoke"])
    p.add_argument("--backbone")
    a = p.parse_args()
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    if a.worker:
        print(json.dumps(worker(a.worker, a.backbone, out)))
    else:
        result = []
        for backbone in ["mobilenet_v3_small", "shufflenet_v2_x0_5"]:
            for mode in ["native", "export", "onnx", "train_smoke"]:
                env = {
                    **os.environ,
                    "OMP_NUM_THREADS": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                }
                r = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        __spec__.name,
                        "--output",
                        str(out),
                        "--worker",
                        mode,
                        "--backbone",
                        backbone,
                    ],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=180,
                )
                if r.returncode:
                    raise RuntimeError(r.stderr)
                result.append(json.loads(r.stdout))
                print(backbone, mode, "OK", flush=True)
        (out / "engineering.json").write_text(json.dumps(result, indent=2))
