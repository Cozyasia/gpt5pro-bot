"""Validate the Apache-2.0 MediaPipe multiclass ownership candidate."""

import argparse, json, resource
from pathlib import Path
import cv2, mediapipe as mp, numpy as np


def _ground_truth(sample, shape):
    mask=np.zeros(shape,np.uint8)
    for polygon in sample["polygons"]:
        cv2.fillPoly(mask,[np.asarray(polygon,np.int32)],1)
    return mask,sample["tags"]


def main(a):
    a.output.mkdir(parents=True,exist_ok=True)
    lo=mp.tasks.vision.FaceLandmarkerOptions(base_options=mp.tasks.BaseOptions(model_asset_path=str(a.landmarker)),num_faces=1)
    so=mp.tasks.vision.ImageSegmenterOptions(base_options=mp.tasks.BaseOptions(model_asset_path=str(a.segmenter)),output_category_mask=True)
    rows=[]
    with mp.tasks.vision.FaceLandmarker.create_from_options(lo) as lm, mp.tasks.vision.ImageSegmenter.create_from_options(so) as sg:
      raw=json.loads(a.ground_truth.read_text())
      for sample in raw["samples"]:
        case,kind=sample["case"],sample["image"]; expected=bool(sample["polygons"])
        ext="jpg" if kind=="source" else "png"; path=a.fixtures/f"{case}_{kind}.{ext}"
        bgr=cv2.imread(str(path)); h,w=bgr.shape[:2]; image=mp.Image(image_format=mp.ImageFormat.SRGB,data=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB))
        pts=np.array([[p.x*w,p.y*h] for p in lm.detect(image).face_landmarks[0]])[:468]
        mask=sg.segment(image).category_mask.numpy_view().copy()
        gt,tags=_ground_truth(sample,(h,w))
        x0,x1=np.percentile(pts[:,0],[5,95]); y0,y1=np.percentile(pts[:,1],[8,55]); x0,x1=max(0,int(x0)),min(w,int(x1)); y0,y1=max(0,int(y0)),min(h,int(y1))
        roi=mask[y0:y1,x0:x1]; pixels=int(np.count_nonzero(roi==5)); fraction=float(pixels/max(1,roi.size)); predicted=fraction>=.01
        predicted_mask=np.zeros_like(mask,dtype=np.uint8); predicted_mask[y0:y1,x0:x1]=(roi==5)
        intersection=int(np.count_nonzero(predicted_mask & gt)); union=int(np.count_nonzero(predicted_mask | gt))
        gt_pixels=int(np.count_nonzero(gt)); pred_pixels=int(np.count_nonzero(predicted_mask))
        precision=intersection/max(1,pred_pixels); recall=intersection/max(1,gt_pixels)
        iou=intersection/max(1,union)
        rows.append({"case":case,"image":kind,"tags":tags,"expected_glasses":expected,"predicted_accessory":predicted,"eye_band_accessory_pixels":pixels,"eye_band_accessory_fraction":fraction,"presence_correct":predicted==expected,"ground_truth_pixels":gt_pixels,"pixel_precision":precision,"pixel_recall":recall,"pixel_iou":iou})
        cv2.imwrite(str(a.output/f"{case}_{kind}_classes.png"),(mask*40).astype(np.uint8))
    positives=[x for x in rows if x["expected_glasses"]]
    ownership_validated=(sum(x["presence_correct"] for x in rows)==len(rows) and len(positives)>=4 and min(x["pixel_iou"] for x in positives)>=.5)
    reason=("Independent coverage and IoU gate passed." if ownership_validated else "Presence is measured, but the frozen fixtures contain only two positive images of one frame; the required four-positive diversity and/or IoU>=0.50 gate is not met.")
    report={"model":"MediaPipe SelfieMulticlass","classes":["background","hair","body-skin","face-skin","clothes","others/accessories"],"presence_correct":sum(x["presence_correct"] for x in rows),"presence_total":len(rows),"positive_images":len(positives),"minimum_required_positive_images":4,"positive_pixel_iou_mean":float(np.mean([x["pixel_iou"] for x in positives])) if positives else 0.0,"independent_pixel_mask_ground_truth":True,"annotation_method":raw["annotation_method"],"ownership_validated":ownership_validated,"reason":reason,"peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,"samples":rows}
    (a.output/"summary.json").write_text(json.dumps(report,indent=2)); print(json.dumps(report,indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--landmarker",type=Path,required=True);p.add_argument("--segmenter",type=Path,required=True);p.add_argument("--fixtures",type=Path,default=Path("tests/fixtures/v265_matrix"));p.add_argument("--ground-truth",type=Path,default=Path("tests/fixtures/v265_glasses_ground_truth.json"));p.add_argument("--output",type=Path,required=True);main(p.parse_args())
