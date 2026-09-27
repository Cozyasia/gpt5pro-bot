"""Local bootstrap observations; model asset is supplied and checksum pinned."""

import json
from pathlib import Path
import numpy as np
from experiments.v265_prior.ingest import sha

VERSION = "mediapipe-observations-bootstrap-1"


def observe(source_path, asset_path, output):
    import mediapipe as mp

    manifest = json.loads(
        Path("tests/fixtures/v265_commercial_assets.json").read_text()
    )["assets"]["face_landmarker.task"]
    if sha(asset_path) != manifest["sha256"]:
        raise ValueError("observation asset mismatch")
    options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(asset_path)),
        num_faces=2,
        output_face_blendshapes=True,
        output_facial_transformation_matrixes=True,
    )
    with mp.tasks.vision.FaceLandmarker.create_from_options(options) as model:
        image = mp.Image.create_from_file(str(source_path))
        result = model.detect(image)
    records = [
        {
            "landmarks": [[p.x, p.y, p.z] for p in face],
            "blendshapes": {
                c.category_name: c.score for c in result.face_blendshapes[i]
            },
            "transform": result.facial_transformation_matrixes[i].tolist(),
        }
        for i, face in enumerate(result.face_landmarks)
    ]
    # Multiple faces require explicit PERSON-A selection; no automatic ownership guess.
    report = {
        "module_version": VERSION,
        "source_sha256": sha(source_path),
        "model_sha256": manifest["sha256"],
        "faces": records,
        "identity_owner_selection_required": len(records) != 1,
        "glasses_ownership_validated": False,
    }
    Path(output).write_text(json.dumps(report, indent=2))
    return report
