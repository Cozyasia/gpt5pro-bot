"""Run the legally-clear MediaPipe + non-learned residual L2-C benchmark."""

import argparse, hashlib, json, resource
from pathlib import Path
import cv2
import mediapipe as mp
import numpy as np

from neyrobot_prod.v265_commercial_geometry import *


CASES = ("case01","case02","case04","case05","case06","case07","case08")


def detect(landmarker, path):
    bgr = cv2.imread(str(path))
    result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
    if len(result.face_landmarks) != 1:
        raise RuntimeError(f"one face required: {path}")
    points = np.array([[x.x,x.y,x.z] for x in result.face_landmarks[0]], np.float32)[:468]
    blend = {x.category_name: float(x.score) for x in result.face_blendshapes[0]}
    return points, blend


def main(a):
    a.output.mkdir(parents=True, exist_ok=True)
    template, triangles = load_canonical_obj(a.canonical)
    opts = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(a.model)), num_faces=1,
        output_face_blendshapes=True, output_facial_transformation_matrixes=True)
    rows=[]
    with mp.tasks.vision.FaceLandmarker.create_from_options(opts) as landmarker:
        for case in CASES:
            source, source_blend = detect(landmarker, a.fixtures/f"{case}_source.jpg")
            target, target_blend = detect(landmarker, a.fixtures/f"{case}_stage1.png")
            sc, st = canonicalize(template, source); tc, tt = canonicalize(template, target)
            identity, source_expression, q = fit_identity(template, sc)
            final, target_expression = retarget(template, identity, q, tc)
            self_recon = template + identity + source_expression
            projected = project(final, tt)
            src_m, target_m, final_m = semantic_metrics(source), semantic_metrics(target), semantic_metrics(projected)
            topo = topology_metrics(template+identity, final, triangles)
            row={"case":case,"identity_hash":residual_digest(identity),
                 "source_self_rmse_iod":float(np.sqrt(np.mean((project(self_recon,st)[:,:2]-source[:,:2])**2))/np.linalg.norm(source[33,:2]-source[263,:2])),
                 "source":src_m,"target":target_m,"retarget":final_m,"topology":topo,
                 "mouth_identity_width_error":abs(final_m["mouth_width"]-src_m["mouth_width"]),
                 "mouth_identity_philtrum_error":abs(final_m["philtrum"]-src_m["philtrum"]),
                 "mouth_identity_chin_error":abs(final_m["mouth_chin"]-src_m["mouth_chin"]),
                 "target_opening_error":abs(final_m["opening"]-target_m["opening"]),
                 "blendshapes":{"source_jawOpen":source_blend.get("jawOpen"),"target_jawOpen":target_blend.get("jawOpen"),"source_smile":np.mean([source_blend.get("mouthSmileLeft",0),source_blend.get("mouthSmileRight",0)]),"target_smile":np.mean([target_blend.get("mouthSmileLeft",0),target_blend.get("mouthSmileRight",0)])}}
            rows.append(row); (a.output/f"{case}.json").write_text(json.dumps(row,indent=2))
    repeated={"case01_case05":rows[0]["identity_hash"]==rows[3]["identity_hash"],"case02_case06":rows[1]["identity_hash"]==rows[4]["identity_hash"]}
    summary={"architecture":"MediaPipe FaceMesh + expression-orthogonal bounded non-learned canonical 3D residual","model_sha256":hashlib.sha256(a.model.read_bytes()).hexdigest(),"canonical_sha256":hashlib.sha256(a.canonical.read_bytes()).hexdigest(),"model_bytes":a.model.stat().st_size,"canonical_bytes":a.canonical.stat().st_size,"peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,"repeated_identity":repeated,"cases":rows}
    (a.output/"summary.json").write_text(json.dumps(summary,indent=2)); print(json.dumps(summary,indent=2))


if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("--model",type=Path,required=True); p.add_argument("--canonical",type=Path,required=True); p.add_argument("--fixtures",type=Path,default=Path("tests/fixtures/v265_matrix")); p.add_argument("--output",type=Path,required=True); main(p.parse_args())
