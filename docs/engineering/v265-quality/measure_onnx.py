"""Run separately per ONNX artifact to avoid allocator/RSS carry-over."""

import argparse, json, resource, time, hashlib
from pathlib import Path
import numpy as np
import onnxruntime as ort

p = argparse.ArgumentParser()
p.add_argument("model")
p.add_argument("record")
p.add_argument("output")
a = p.parse_args()
with np.load(a.record) as r:
    x = r["rgb"].transpose(2, 0, 1)[None].astype("float32")
opt = ort.SessionOptions()
opt.intra_op_num_threads = 2
opt.inter_op_num_threads = 1
start = time.perf_counter()
session = ort.InferenceSession(a.model, opt, providers=["CPUExecutionProvider"])
cold = (time.perf_counter() - start) * 1000
first = session.run(None, {"rgb": x})
start = time.perf_counter()
for _ in range(100):
    last = session.run(None, {"rgb": x})
result = dict(
    cold_session_ms=cold,
    warm_inference_ms=(time.perf_counter() - start) * 10,
    peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    deterministic=all(np.array_equal(x, y) for x, y in zip(first, last)),
    onnx_sha256=hashlib.sha256(Path(a.model).read_bytes()).hexdigest(),
    isolated_memory_limit=False,
)
Path(a.output).write_text(json.dumps(result, indent=2))
print(json.dumps(result))
