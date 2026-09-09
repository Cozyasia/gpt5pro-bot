"""Pin and convert research-only L2 assets into a geometry-only FaceVerse pack."""

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
import numpy as np


ASSETS = {
    "faceverse_v4_2.npy": (
        "https://github.com/Mrkomiljon/faceverse-onnx/releases/download/v4.1.0/faceverse_v4_2.npy",
        "077df2658add90ea22ac9675967e38edf56170822c2a7acfe40bda55a9ed3702",
    ),
    "faceverse_resnet50_int8.onnx": (
        "https://github.com/Mrkomiljon/faceverse-onnx/releases/download/v4.1.0/faceverse_resnet50_int8.onnx",
        "d3b2deb3d99ceb254fa20dbb5b42bed35850da9ff0206502395bf1b09df9f5f8",
    ),
    "face_parsing_resnet18.onnx": (
        "https://github.com/yakhyo/face-parsing/releases/download/weights/resnet18.onnx",
        "0d9bd318e46987c3bdbfacae9e2c0f461cae1c6ac6ea6d43bbe541a91727e33f",
    ),
}


def fetch(path, url, digest):
    if not path.exists():
        with urllib.request.urlopen(url, timeout=180) as response:
            path.write_bytes(response.read())
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != digest:
        raise ValueError(f"asset hash mismatch {path.name}: {actual}")


def run(a):
    a.output.mkdir(parents=True, exist_ok=True)
    for name, (url, digest) in ASSETS.items():
        fetch(a.output / name, url, digest)
    raw = np.load(a.output / "faceverse_v4_2.npy", allow_pickle=True).item()
    np.savez_compressed(
        a.output / "faceverse_geometry.npz",
        mean=raw["meanshape"].astype(np.float32) / 100,
        identity_basis=raw["idBase"].reshape(-1, 3, 156).astype(np.float32) / 100,
        expression_basis=raw["exBase"].reshape(-1, 3, 177).astype(np.float32) / 100,
        triangles=raw["tri"].astype(np.int32),
        landmarks=raw["keypoints_68"].astype(np.int32),
        face_mask=raw["face_mask"].astype(np.uint8),
    )
    report = {
        "research_only": True,
        "commercial_asset_license_verified": False,
        "source_model_bytes": (a.output / "faceverse_v4_2.npy").stat().st_size,
        "regressor_bytes": (a.output / "faceverse_resnet50_int8.onnx").stat().st_size,
        "parsing_model_bytes": (a.output / "face_parsing_resnet18.onnx").stat().st_size,
        "geometry_pack_bytes": (a.output / "faceverse_geometry.npz").stat().st_size,
        "identity_dimensions": 156,
        "expression_dimensions": 177,
        "vertices": int(raw["meanshape"].shape[0]),
        "triangles": int(raw["tri"].shape[0]),
        "texture_basis_excluded": True,
    }
    (a.output / "asset_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args())
