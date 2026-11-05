"""Offline detector-scale consensus; not the runtime face selector.

The existing selector keeps whichever scale reports the largest box. This lab
uses median coordinates only when all scale detections overlap the median box.
No inference is made about identity/pose eligibility from detector agreement.
"""

import cv2
import numpy as np
from . import selfie_v263_dense_identity_lock as dense


def landmarks(image, models):
    h, w = image.shape[:2]
    boxes = []
    for side in (640.0, 512.0, 448.0, 384.0):
        scale = min(1.0, side / max(h, w))
        rw = max(96, round(w * scale))
        rh = max(96, round(h * scale))
        frame = cv2.resize(image, (rw, rh), interpolation=cv2.INTER_AREA)
        detector = cv2.FaceDetectorYN.create(
            str(models / "yunet.onnx"),
            "",
            (rw, rh),
            score_threshold=0.62,
            nms_threshold=0.30,
            top_k=1000,
        )
        _, faces = detector.detect(frame)
        if faces is None:
            continue
        b = max(faces, key=lambda r: float(r[2] * r[3]))[:4].astype(float)
        b *= np.array([w / rw, h / rh, w / rw, h / rh])
        boxes.append(b)
    if len(boxes) < 2:
        raise ValueError("insufficient detector-scale consensus")
    median = np.median(boxes, axis=0)
    for b in boxes:
        lo = np.maximum(b[:2], median[:2])
        hi = np.minimum(b[:2] + b[2:], median[:2] + median[2:])
        intersection = np.maximum(hi - lo, 0).prod()
        iou = intersection / (b[2:].prod() + median[2:].prod() - intersection)
        if iou < 0.5:
            raise ValueError("ambiguous detector-scale association")
    return dense._dense_landmarks_68(
        image, median, models / "pipnet.onnx", label="offline_scale_consensus"
    )
