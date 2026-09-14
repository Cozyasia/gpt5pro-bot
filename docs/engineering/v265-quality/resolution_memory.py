"""NEW dense-resolution engineering microbenchmark; not trained quality evidence."""

import argparse, json, time, resource, hashlib
from pathlib import Path
import numpy as np
import torch
from experiments.v265_quality.factory import surface
from experiments.v265_quality.train import Model

p = argparse.ArgumentParser()
p.add_argument("level", type=int)
p.add_argument("output")
a = p.parse_args()
torch.set_num_threads(2)
torch.manual_seed(1)
s = surface(a.level)
m = Model(s, "mobilenet_v3_small", 128, "parametric", 64)
opt = torch.optim.AdamW(m.parameters())
x = torch.rand(16, 3, 64, 64)
start = time.perf_counter()
v, c, alb, seg = m(x)
loss = v.square().mean() + c.square().mean() + alb.square().mean() + seg.square().mean()
loss.backward()
opt.step()
training_ms = (time.perf_counter() - start) * 1000
m.eval()
out = Path(a.output)
out.mkdir(parents=True, exist_ok=True)
onnx = out / "scale.onnx"
torch.onnx.export(
    m,
    x[:1],
    onnx,
    opset_version=17,
    input_names=["rgb"],
    output_names=["canonical", "coefficients", "albedo", "parsing"],
)
r = dict(
    level=a.level,
    vertices=len(s["neutral"]),
    single_update_batch=16,
    single_update_ms=training_ms,
    process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    model_bytes=sum(p.numel() * p.element_size() for p in m.parameters()),
    buffers_bytes=sum(p.numel() * p.element_size() for p in m.buffers()),
    onnx_bytes=onnx.stat().st_size,
    onnx_sha256=hashlib.sha256(onnx.read_bytes()).hexdigest(),
    quality_evidence=False,
    full_training_run=False,
)
(out / "scale.json").write_text(json.dumps(r, indent=2))
print(json.dumps(r))
