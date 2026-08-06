# -*- coding: utf-8 -*-
"""V242 non-fatal target lock for the terminal Celebrity Selfie pipeline.

Gemini still creates scene, hero and body. Photo #3 remains the only identity source.
This patch removes the fatal `detected=0`/`detected=1` gate after Gemini generation:
when OpenCV cannot detect both faces, PERSON A is locked by the deterministic LEFT-side
layout required by the stage-one prompt, then PiAPI receives a one-person crop.
"""
from __future__ import annotations

from typing import Any

VERSION = "v242-nonfatal-left-target-lock-2026-08-06"
_INSTALLED = False


def _heuristic_left_face_box(image_size: tuple[int, int]) -> tuple[int, int, int, int]:
    """Return a conservative synthetic face box for PERSON A on the left.

    Stage-one generation explicitly requires PERSON A on the left, near-frontal, with
    both heads in the upper half. The box is used only when detectors cannot reliably
    locate PERSON A; it never generates identity and never touches the hero.
    """
    width, height = image_size
    face_w = max(84, int(min(width * 0.18, height * 0.20)))
    face_h = max(96, int(face_w * 1.12))
    cx = int(width * 0.29)
    cy = int(height * 0.30)
    x = max(0, min(width - face_w, cx - face_w // 2))
    y = max(0, min(height - face_h, cy - face_h // 2))
    return int(x), int(y), int(face_w), int(face_h)


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    from neyrobot_prod import selfie_v234_terminal_user_transfer as v237

    def nonfatal_target_face_crop(
        raw: bytes,
    ) -> tuple[Any, tuple[int, int, int, int], bytes, tuple[int, int, int, int]]:
        image = v237._image(raw)
        faces = list(v237._detect_faces(image) or [])
        width, height = image.size

        # Keep only plausible principal faces. Background detections must not steal
        # the target slot from PERSON A.
        substantial = [
            box for box in faces
            if box[2] >= max(58, int(width * 0.045))
            and box[3] >= max(58, int(height * 0.035))
            and (box[1] + box[3] / 2.0) < height * 0.66
        ]
        substantial.sort(key=lambda box: box[0] + box[2] / 2.0)

        detector_mode = "opencv_left_main"
        target_face: tuple[int, int, int, int]
        if substantial:
            left_candidate = substantial[0]
            center_x = left_candidate[0] + left_candidate[2] / 2.0
            # A single right-side detection is usually the hero. Do not swap it.
            if center_x <= width * 0.56:
                target_face = left_candidate
            else:
                target_face = _heuristic_left_face_box(image.size)
                detector_mode = "deterministic_left_fallback_right_only"
        else:
            target_face = _heuristic_left_face_box(image.size)
            detector_mode = "deterministic_left_fallback_no_faces"

        crop_box = v237._expanded_box(
            target_face,
            image.size,
            width_factor=2.75,
            height_factor=3.25,
            y_shift=0.04,
        )
        crop = image.crop(crop_box)
        crop_raw = v237._jpeg(crop, max_side=1500)

        print(
            f"[neyrobot-prod] AI_SELFIE_V242_TARGET_LOCK mode={detector_mode} "
            f"image={image.size} detected={len(faces)} substantial={len(substantial)} "
            f"target_face={target_face} crop_box={crop_box} crop_bytes={len(crop_raw)}",
            flush=True,
        )
        return image, crop_box, crop_raw, target_face

    v237._target_face_crop = nonfatal_target_face_crop
    v237.VERSION = VERSION
    _INSTALLED = True
    print(f"[neyrobot-prod] V242 non-fatal target lock installed version={VERSION}", flush=True)
    return True


install()

__all__ = ["VERSION", "install"]
