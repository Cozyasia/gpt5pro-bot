"""Isolated local observations + own encoder + sequential parsing, public fixture only."""

import argparse, ctypes, gc, json, time
from pathlib import Path
import numpy as np
from PIL import Image
from experiments.v265_prior.ingest import sha
from experiments.v265_prior.benchmark import memory


def run(assets, model, source, output):
    import mediapipe as mp
    import onnxruntime as ort

    assets = Path(assets)
    model = Path(model)
    manifest = json.loads(
        Path("tests/fixtures/v265_commercial_assets.json").read_text()
    )["assets"]
    for name in ["face_landmarker.task", "selfie_multiclass_256x256.tflite"]:
        if sha(assets / name) != manifest[name]["sha256"]:
            raise ValueError("bootstrap model hash")
    meta = json.loads((model / "model-manifest.json").read_text())
    report = {
        "scope": "public case02 bootstrap plus own TEST ONLY encoder; not identity qualification",
        "stages": [],
    }
    image = mp.Image.create_from_file(str(source))
    report["source_sha256"] = sha(source)
    lo = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(assets / "face_landmarker.task")
        ),
        num_faces=1,
        output_face_blendshapes=True,
        output_facial_transformation_matrixes=True,
    )
    with mp.tasks.vision.FaceLandmarker.create_from_options(lo) as lm:
        detected = lm.detect(image)
        if len(detected.face_landmarks) != 1:
            raise ValueError("public face not observed")
        op = ort.SessionOptions()
        op.intra_op_num_threads = 1
        op.inter_op_num_threads = 1
        session = ort.InferenceSession(
            str(model / "identity.onnx"),
            sess_options=op,
            providers=["CPUExecutionProvider"],
        )
        h, w = meta["input_size"][2:]
        rgb = (
            np.asarray(Image.open(source).convert("RGB").resize((w, h)))
            .transpose(2, 0, 1)[None]
            .astype("float32")
            / 255
        )
        session.run(None, {"rgb": rgb})
        report["stages"].append({"name": "mediapipe_plus_own_encoder", **memory()})
        del session
    gc.collect()
    ctypes.CDLL("libc.so.6").malloc_trim(0)
    report["stages"].append({"name": "after_release", **memory()})
    so = mp.tasks.vision.ImageSegmenterOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(assets / "selfie_multiclass_256x256.tflite")
        ),
        output_category_mask=True,
    )
    with mp.tasks.vision.ImageSegmenter.create_from_options(so) as parser:
        result = parser.segment(image)
        report["mask_shape"] = list(result.category_mask.numpy_view().shape)
        report["stages"].append({"name": "sequential_bootstrap_parsing", **memory()})
    report["commercial_ownership_validated"] = False
    report["memory_swap_max"] = (
        Path("/sys/fs/cgroup/memory.swap.max").read_text().strip()
    )
    report["memory_events"] = Path("/sys/fs/cgroup/memory.events").read_text()
    Path(output).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("assets")
    p.add_argument("model")
    p.add_argument("source")
    p.add_argument("output")
    a = p.parse_args()
    run(a.assets, a.model, a.source, a.output)
