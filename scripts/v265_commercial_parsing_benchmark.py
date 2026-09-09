"""Validate the Apache-2.0 MediaPipe multiclass ownership candidate."""

import argparse, json, resource
from pathlib import Path
import cv2, mediapipe as mp, numpy as np


SAMPLES=(("case07","source",True),("case07","stage1",True),("case01","source",False),
         ("case02","source",False),("case04","source",False),("case08","source",False))


def main(a):
    a.output.mkdir(parents=True,exist_ok=True)
    lo=mp.tasks.vision.FaceLandmarkerOptions(base_options=mp.tasks.BaseOptions(model_asset_path=str(a.landmarker)),num_faces=1)
    so=mp.tasks.vision.ImageSegmenterOptions(base_options=mp.tasks.BaseOptions(model_asset_path=str(a.segmenter)),output_category_mask=True)
    rows=[]
    with mp.tasks.vision.FaceLandmarker.create_from_options(lo) as lm, mp.tasks.vision.ImageSegmenter.create_from_options(so) as sg:
      for case,kind,expected in SAMPLES:
        ext="jpg" if kind=="source" else "png"; path=a.fixtures/f"{case}_{kind}.{ext}"
        bgr=cv2.imread(str(path)); h,w=bgr.shape[:2]; image=mp.Image(image_format=mp.ImageFormat.SRGB,data=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB))
        pts=np.array([[p.x*w,p.y*h] for p in lm.detect(image).face_landmarks[0]])[:468]
        mask=sg.segment(image).category_mask.numpy_view().copy()
        x0,x1=np.percentile(pts[:,0],[5,95]); y0,y1=np.percentile(pts[:,1],[8,55]); x0,x1=max(0,int(x0)),min(w,int(x1)); y0,y1=max(0,int(y0)),min(h,int(y1))
        roi=mask[y0:y1,x0:x1]; pixels=int(np.count_nonzero(roi==5)); fraction=float(pixels/max(1,roi.size)); predicted=fraction>=.01
        rows.append({"case":case,"image":kind,"expected_glasses":expected,"predicted_accessory":predicted,"eye_band_accessory_pixels":pixels,"eye_band_accessory_fraction":fraction,"presence_correct":predicted==expected})
        cv2.imwrite(str(a.output/f"{case}_{kind}_classes.png"),(mask*40).astype(np.uint8))
    report={"model":"MediaPipe SelfieMulticlass","classes":["background","hair","body-skin","face-skin","clothes","others/accessories"],"presence_correct":sum(x["presence_correct"] for x in rows),"presence_total":len(rows),"independent_pixel_mask_ground_truth":False,"ownership_validated":False,"reason":"Accessory pixels are explicit, but the broad others/accessories class has no independent glasses pixel-mask ground truth.","peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,"samples":rows}
    (a.output/"summary.json").write_text(json.dumps(report,indent=2)); print(json.dumps(report,indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--landmarker",type=Path,required=True);p.add_argument("--segmenter",type=Path,required=True);p.add_argument("--fixtures",type=Path,default=Path("tests/fixtures/v265_matrix"));p.add_argument("--output",type=Path,required=True);main(p.parse_args())
