"""Offline lifecycle measurement. Blank image exercises models, not face-fit quality."""

import argparse
import ctypes
import gc
import json
from pathlib import Path
import numpy as np
from .benchmark import memory
from .ingest import sha


def run(assets, encoder, source):
    import mediapipe as mp
    import onnxruntime as ort

    manifest = json.loads(
        Path("tests/fixtures/v265_commercial_assets.json").read_text()
    )["assets"]
    for name in ["face_landmarker.task", "selfie_multiclass_256x256.tflite"]:
        if sha(Path(assets) / name) != manifest[name]["sha256"]:
            raise ValueError("model checksum")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    result = {
        "scope": "public frozen case02 model inference; no full application qualification",
        "source_sha256": sha(source),
        "imported_frameworks": memory(),
        "stages": [],
    }
    image = mp.Image.create_from_file(str(source))
    lmopt = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(Path(assets) / "face_landmarker.task")
        ),
        output_face_blendshapes=True,
        output_facial_transformation_matrixes=True,
        num_faces=1,
    )
    with mp.tasks.vision.FaceLandmarker.create_from_options(lmopt) as lm:
        detection = lm.detect(image)
        result["faces_detected"] = len(detection.face_landmarks)
        if not detection.face_landmarks:
            raise ValueError("no public fixture face detected")
        session = ort.InferenceSession(
            str(encoder), sess_options=options, providers=["CPUExecutionProvider"]
        )
        session.run(None, {"rgb": np.zeros((1, 3, 224, 224), np.float32)})
        result["stages"].append({"stage": "landmarker_plus_encoder", **memory()})
        del session
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:
        pass
    result["stages"].append({"stage": "after_fit_close_trim", **memory()})
    segopt = mp.tasks.vision.ImageSegmenterOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(Path(assets) / "selfie_multiclass_256x256.tflite")
        ),
        output_category_mask=True,
    )
    with mp.tasks.vision.ImageSegmenter.create_from_options(segopt) as seg:
        seg.segment(image)
        result["stages"].append({"stage": "sequential_parsing", **memory()})
    result["two_gib_limit_enforced"] = False
    result["production_memory_qualified"] = False
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("assets")
    p.add_argument("encoder")
    p.add_argument("output")
    p.add_argument("--source", default="tests/fixtures/v265_matrix/case02_source.jpg")
    a = p.parse_args()
    r = run(a.assets, a.encoder, a.source)
    Path(a.output).write_text(json.dumps(r, indent=2))
    print(json.dumps(r, indent=2))
