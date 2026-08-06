# -*- coding: utf-8 -*-
"""V241 resilient face acquisition for the terminal celebrity-selfie pipeline.

This module does not generate a user identity. Gemini remains responsible only for
scene, hero and body. Photo #3 remains the sole identity source for PiAPI FaceSwap.
The patch only prevents a valid portrait from being rejected by the brittle Haar
frontal-face gate used by V237/V238.
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

VERSION = "v241-resilient-terminal-face-detection-2026-08-06"
_INSTALLED = False


def _multi_pass_faces(image: Any) -> list[tuple[int, int, int, int]]:
    """Detect faces with several conservative OpenCV passes.

    Returned boxes are in original-image coordinates and sorted left-to-right.
    No identity generation or image alteration happens here.
    """
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
        from PIL import Image, ImageEnhance

        width, height = image.size
        scale = min(1.0, 1600.0 / float(max(width, height)))
        scan = image
        if scale < 1.0:
            scan = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.LANCZOS)

        rgb = np.asarray(scan)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        equalized = cv2.equalizeHist(gray)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        frontal = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        alt = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml"
        )
        profile = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_profileface.xml"
        )

        candidates: list[tuple[int, int, int, int]] = []
        passes = (
            (frontal, gray, 1.05, 3),
            (frontal, equalized, 1.04, 3),
            (alt, clahe, 1.04, 3),
            (profile, equalized, 1.05, 3),
        )
        min_side = max(36, int(min(scan.size) * 0.055))
        for cascade, frame, factor, neighbors in passes:
            if cascade.empty():
                continue
            found = cascade.detectMultiScale(
                frame,
                scaleFactor=factor,
                minNeighbors=neighbors,
                minSize=(min_side, min_side),
            )
            for x, y, w, h in found:
                candidates.append((int(x), int(y), int(w), int(h)))

        # Profile cascade only detects one direction; mirror and map back.
        if not profile.empty():
            mirrored = cv2.flip(equalized, 1)
            found = profile.detectMultiScale(
                mirrored,
                scaleFactor=1.05,
                minNeighbors=3,
                minSize=(min_side, min_side),
            )
            sw = scan.size[0]
            for x, y, w, h in found:
                candidates.append((int(sw - x - w), int(y), int(w), int(h)))

        # Non-maximum suppression without requiring opencv-contrib.
        candidates.sort(key=lambda b: b[2] * b[3], reverse=True)
        kept: list[tuple[int, int, int, int]] = []
        for box in candidates:
            x, y, w, h = box
            area = float(w * h)
            duplicate = False
            for kx, ky, kw, kh in kept:
                ix1, iy1 = max(x, kx), max(y, ky)
                ix2, iy2 = min(x + w, kx + kw), min(y + h, ky + kh)
                inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                union = area + float(kw * kh) - float(inter)
                if union and inter / union > 0.35:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(box)

        inverse = 1.0 / scale
        result = [
            (
                int(round(x * inverse)),
                int(round(y * inverse)),
                int(round(w * inverse)),
                int(round(h * inverse)),
            )
            for x, y, w, h in kept
        ]
        result.sort(key=lambda b: b[0] + b[2] / 2.0)
        return result
    except Exception:
        return []


def _portrait_fallback_box(image: Any) -> tuple[int, int, int, int]:
    """Deterministic portrait fallback used only when detectors return no box.

    Photo #3 is explicitly requested as a large portrait. The fallback therefore
    crops the central upper face region instead of aborting or invoking Gemini.
    """
    width, height = image.size
    side = int(min(width * 0.58, height * 0.58))
    side = max(128, min(side, width, height))
    cx = width // 2
    cy = int(height * 0.39)
    x = max(0, min(width - side, cx - side // 2))
    y = max(0, min(height - side, cy - side // 2))
    return int(x), int(y), int(side), int(side)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    from neyrobot_prod import selfie_v234_terminal_user_transfer as v237
    from neyrobot_prod import selfie_v238_observable_double_transfer as v238

    original_detect = v237._detect_faces

    def resilient_detect(image: Any) -> list[tuple[int, int, int, int]]:
        faces = _multi_pass_faces(image)
        if faces:
            return faces
        return original_detect(image)

    def resilient_source_crop(raw: bytes) -> tuple[bytes, tuple[int, int, int, int]]:
        image = v237._image(raw)
        faces = resilient_detect(image)
        detector = "opencv_multi_pass"
        if faces:
            box = max(faces, key=lambda item: item[2] * item[3])
        else:
            box = _portrait_fallback_box(image)
            detector = "deterministic_portrait_fallback"
        crop_box = v237._expanded_box(
            box,
            image.size,
            width_factor=2.05,
            height_factor=2.40,
            y_shift=-0.03,
        )
        crop = v237._jpeg(image.crop(crop_box), max_side=1200)
        print(
            f"[neyrobot-prod] AI_SELFIE_V241 source_face detector={detector} "
            f"image={image.size} face_box={box} crop_box={crop_box}",
            flush=True,
        )
        return crop, box

    def resilient_tight_crop(
        raw: bytes,
        *,
        wf: float,
        hf: float,
        ys: float = 0.0,
    ) -> tuple[Any, tuple[int, int, int, int], bytes, tuple[int, int, int, int]]:
        image = v237._image(raw)
        faces = resilient_detect(image)
        detector = "opencv_multi_pass"
        if faces:
            face = max(faces, key=lambda item: item[2] * item[3])
        else:
            face = _portrait_fallback_box(image)
            detector = "deterministic_portrait_fallback"
        box = v237._expanded_box(
            face,
            image.size,
            width_factor=wf,
            height_factor=hf,
            y_shift=ys,
        )
        crop = v237._jpeg(image.crop(box), max_side=1100)
        print(
            f"[neyrobot-prod] AI_SELFIE_V241 tight_face detector={detector} "
            f"image={image.size} face_box={face} crop_box={box}",
            flush=True,
        )
        return image, box, crop, face

    v237._detect_faces = resilient_detect
    v237._source_face_crop = resilient_source_crop
    v238._single_face_tight_crop = resilient_tight_crop
    v237.VERSION = VERSION
    v238.VERSION = "v241-v238-resilient-double-terminal-face-transfer-2026-08-06"
    _INSTALLED = True
    print(f"[neyrobot-prod] V241 resilient terminal face detector installed version={VERSION}", flush=True)
    return True


install()

__all__ = ["VERSION", "install"]
