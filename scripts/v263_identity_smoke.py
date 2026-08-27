# -*- coding: utf-8 -*-
"""Network-backed V263 identity smoke matrix for GitHub Actions."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import cv2
import numpy as np

from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
from neyrobot_prod import selfie_v262_landmark_field_compositor as v262
from neyrobot_prod import selfie_v263_dense_identity_lock as v263
from neyrobot_prod.selfie_v263_runtime_safety import install as install_runtime_safety


def _read(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"could not read fixture: {path}")
    return image


def _rotate_scale(image: np.ndarray, angle: float, scale: float) -> np.ndarray:
    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w * 0.5, h * 0.5), angle, scale)
    return cv2.warpAffine(image, matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)


def _small_face(image: np.ndarray) -> np.ndarray:
    h, w = image.shape[:2]
    factor = 0.70
    small = cv2.resize(image, (max(96, int(w * factor)), max(96, int(h * factor))), interpolation=cv2.INTER_AREA)
    canvas = np.full_like(image, 118)
    y = max(0, (h - small.shape[0]) // 2)
    x = max(0, (w - small.shape[1]) // 2)
    canvas[y:y + small.shape[0], x:x + small.shape[1]] = small
    return canvas


def _large_face(image: np.ndarray) -> np.ndarray:
    h, w = image.shape[:2]
    mx, my = int(w * 0.10), int(h * 0.10)
    crop = image[my:h - my, mx:w - mx]
    return cv2.resize(crop, (w, h), interpolation=cv2.INTER_LANCZOS4)


def _complex_light(image: np.ndarray) -> np.ndarray:
    x = image.astype(np.float32) / 255.0
    x = np.power(np.clip(x, 0.0, 1.0), 0.72)
    x[:, :, 2] *= 1.12
    x[:, :, 0] *= 0.90
    return np.clip(x * 255.0, 0, 255).astype(np.uint8)


def _two_person(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    height, width = max(720, left.shape[0], right.shape[0]), 1400
    half = width // 2
    canvas = np.full((height, width, 3), 128, dtype=np.uint8)
    for image, x0 in ((left, 0), (right, half)):
        scale = min((half * 0.92) / image.shape[1], (height * 0.96) / image.shape[0])
        resized = cv2.resize(
            image,
            (max(96, int(image.shape[1] * scale)), max(96, int(image.shape[0] * scale))),
            interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LANCZOS4,
        )
        y0 = (height - resized.shape[0]) // 2
        px = x0 + (half - resized.shape[1]) // 2
        canvas[y0:y0 + resized.shape[0], px:px + resized.shape[1]] = resized
    return canvas


def _case_metrics(source: np.ndarray, target: np.ndarray, yunet: Path, dense_model: Path, recognition_model: Path, *, label: str) -> dict[str, float]:
    sb, s5 = v253._yunet_face(source, yunet, label=f"smoke_source_{label}")
    tb, t5 = v253._yunet_face(target, yunet, label=f"smoke_target_{label}")
    sd = v263._dense_landmarks_68(source, sb, dense_model, label=f"smoke_source_{label}")
    td = v263._dense_landmarks_68(target, tb, dense_model, label=f"smoke_target_{label}")
    matrix, _ = v263._similarity_transform(s5, t5)
    projected = v262._project_points(matrix, sd)
    desired = v263._desired_identity_geometry(projected, td, float(min(tb[2], tb[3])), strict=False)
    se = v263._mobileface_embedding(source, sd, recognition_model)
    te = v263._mobileface_embedding(target, td, recognition_model)
    return v263._quality_metrics(se, te, desired, td)


async def _models() -> tuple[Path, Path, Path]:
    install_runtime_safety()
    yunet = await v253._ensure_yunet_model()
    dense, recognition = await v263._ensure_identity_models()
    return yunet, dense, recognition


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    yunet, dense_model, recognition_model = asyncio.run(_models())

    male = _read(args.fixtures / "verify_now_2024.jpg")
    female = _read(args.fixtures / "verify_curie.jpg")
    turn = _read(args.fixtures / "pose_left.jpg")
    einstein = _read(args.fixtures / "verify_einstein_1921.jpg")

    cases = [
        ("frontal_male", male, _rotate_scale(male, 0.0, 1.0)),
        ("slight_turn", turn, _rotate_scale(turn, 4.0, 1.0)),
        ("frontal_female", female, _rotate_scale(female, -2.0, 1.0)),
        ("large_face", einstein, _large_face(einstein)),
        ("small_face", male, _small_face(male)),
        ("complex_light", male, _complex_light(male)),
    ]

    results: dict[str, object] = {}
    passed = 0
    for label, source, target in cases:
        metrics = _case_metrics(source, target, yunet, dense_model, recognition_model, label=label)
        ok, failures = v263._quality_gate(metrics)
        results[label] = {"passed": ok, "failures": failures, **{k: round(float(v), 6) for k, v in metrics.items()}}
        passed += int(ok)
        print("V263_SMOKE", label, json.dumps(results[label], sort_keys=True), flush=True)

    stage1 = _two_person(male, female)
    ok_src, src_png = cv2.imencode(".png", male)
    ok_stage, stage_png = cv2.imencode(".png", stage1)
    if not ok_src or not ok_stage:
        raise RuntimeError("fixture PNG encoding failed")
    output, two_metrics, _ = v263._transfer_attempt(bytes(stage_png), bytes(src_png), yunet, dense_model, recognition_model, strict=False)
    final = v253._decode_bgr(output)
    firewall_x = max(256, min(stage1.shape[1], int(round(stage1.shape[1] * 0.55))))
    person_b_untouched = bool(np.array_equal(final[:, firewall_x:], stage1[:, firewall_x:]))
    two_ok, two_failures = v263._quality_gate(two_metrics)
    results["two_person"] = {
        "passed": two_ok and person_b_untouched,
        "person_b_untouched": person_b_untouched,
        "failures": two_failures,
        **{k: round(float(v), 6) for k, v in two_metrics.items()},
    }
    passed += int(bool(results["two_person"]["passed"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    print("V263_SMOKE two_person", json.dumps(results["two_person"], sort_keys=True), flush=True)

    total = len(cases) + 1
    print(f"V263_SMOKE_SUMMARY accepted={passed}/{total} minimum_required=6/7", flush=True)
    print(json.dumps(results, indent=2, sort_keys=True), flush=True)
    if passed < 6:
        raise SystemExit(f"V263 normal-class acceptance too low: {passed}/{total}")
    if not person_b_untouched:
        raise SystemExit("V263 PERSON-B pixel lock failed in two-person smoke")


if __name__ == "__main__":
    main()
