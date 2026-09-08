"""Reproduce offline 3DDFA V2 asset conversion; no models enter the repository.

Needs torch CPU and onnx ONLY for export. Runtime experiment uses NumPy/ORT.
Upstream code MIT; BFM and checkpoint rights must be reviewed separately before
commercial runtime use. The manifest does not assert commercial clearance.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import urllib.request
import numpy as np


class ArrayUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        allowed = {
            ("numpy", "ndarray"): np.ndarray,
            ("numpy", "dtype"): np.dtype,
            ("numpy.core.multiarray", "_reconstruct"): np.core.multiarray._reconstruct,
        }
        if (module, name) not in allowed:
            raise ValueError("unexpected serialized global: " + module + "." + name)
        return allowed[module, name]


def run(a):
    spec = json.loads(a.manifest.read_text())
    a.output.mkdir(parents=True, exist_ok=True)
    for name, row in spec["assets"].items():
        path = a.output / name
        if not path.exists():
            with urllib.request.urlopen(row["url"], timeout=90) as response:
                path.write_bytes(response.read())
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("asset hash mismatch: " + name)

    def read(name):
        with (a.output / name).open("rb") as f:
            return ArrayUnpickler(f).load()

    b, params, tri = read("bfm.pkl"), read("param.pkl"), read("tri.pkl")
    # bfm.pkl includes obsolete full-head triangle indices; use the official
    # separate no-neck topology. CanonicalModel rejects invalid indices.
    np.savez(
        a.output / "canonical.npz",
        mean=b["u"].reshape(-1, 3),
        identity_basis=b["w_shp"].reshape(-1, 3, 40),
        expression_basis=b["w_exp"].reshape(-1, 3, 10),
        triangles=tri.T,
        landmarks=b["keypoints"][::3] // 3,
        param_mean=params["mean"],
        param_std=params["std"],
    )
    import torch

    spec = importlib.util.spec_from_file_location(
        "verified_upstream_mobile", a.output / "mobilenet_v1.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    network = module.mobilenet(widen_factor=0.5, num_classes=62).eval()
    state = torch.load(
        a.output / "regressor.pth", map_location="cpu", weights_only=True
    )["state_dict"]
    state = {
        k.removeprefix("module.").replace("fc_param.", "fc."): v
        for k, v in state.items()
        if "fc_lm." not in k
    }
    network.load_state_dict(state, strict=True)
    torch.set_num_threads(1)
    x = torch.zeros(1, 3, 120, 120)
    torch.onnx.export(
        network,
        x,
        str(a.output / "regressor.onnx"),
        input_names=["input"],
        output_names=["parameters"],
        opset_version=13,
        dynamo=False,
    )
    import onnxruntime as ort

    sess = ort.InferenceSession(
        str(a.output / "regressor.onnx"), providers=["CPUExecutionProvider"]
    )
    with torch.no_grad():
        for seed in (0, 265):
            torch.manual_seed(seed)
            x = torch.rand(1, 3, 120, 120) * 2 - 1
            np.testing.assert_allclose(
                sess.run(None, {"input": x.numpy()})[0],
                network(x).numpy(),
                rtol=1e-4,
                atol=1e-5,
            )
    print(
        "Export parity PASS; model bytes", (a.output / "regressor.onnx").stat().st_size
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "--manifest",
        type=Path,
        default=Path("tests/fixtures/v265_canonical_assets.json"),
    )
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args())
