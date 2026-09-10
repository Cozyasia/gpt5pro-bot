"""Prepare pinned public models and one normalized Stage-1 before worker processes."""

import argparse, hashlib, json, time, urllib.request
from pathlib import Path
import cv2

MODELS = {
    "pipnet.onnx": (
        "https://github.com/yakhyo/pipnet-onnx/releases/download/weights/pipnet_r18_300w_celeba_68.onnx",
        "63fa56fd4b8f6ccc4b88f2b36e00fa3d8c21a2c4244ab9381e8b432cef35197b",
    ),
    "mobileface.onnx": (
        "https://github.com/yakhyo/uniface/releases/download/weights/mobilenetv2.onnx",
        "38b148284dd48cc898d5d4453104252fbdcbacc105fe3f0b80e78954d9d20d89",
    ),
    "yunet.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
}


def run(a):
    a.models.mkdir(parents=True, exist_ok=True)
    for name, (url, digest) in MODELS.items():
        path = a.models / name
        if not path.exists():
            for attempt in range(4):
                try:
                    with urllib.request.urlopen(url, timeout=90) as r:
                        path.write_bytes(r.read())
                    break
                except OSError:
                    if attempt == 3:
                        raise
                    time.sleep(attempt + 1)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("model hash mismatch: " + name)
    folder = a.output / a.case
    folder.mkdir(parents=True, exist_ok=True)
    fixture = a.fixtures / (a.case + "_stage1.png")
    manifest = json.loads((a.fixtures / "manifest.json").read_text())
    expected = manifest["files"][fixture.name]["sha256"]
    if hashlib.sha256(fixture.read_bytes()).hexdigest() != expected:
        raise ValueError("Stage-1 fixture hash mismatch")
    im = cv2.imread(str(fixture))
    im = cv2.resize(im, (1856, 2304), interpolation=cv2.INTER_LANCZOS4)
    raw = cv2.imencode(".png", im, [cv2.IMWRITE_PNG_COMPRESSION, 2])[1].tobytes()
    path = folder / "stage1.png"
    if path.exists() and path.read_bytes() != raw:
        raise ValueError("frozen normalized bytes changed")
    path.write_bytes(raw)
    print("NORMALIZED_STAGE1_SHA256", hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--fixtures", type=Path, default=Path("tests/fixtures/v265_matrix"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--case", required=True)
    run(p.parse_args())
