# -*- coding: utf-8 -*-
"""V263 production-size (~1856x2304) public-fixture diagnostic.

No user images, credentials or Telegram traffic are used. The purpose is to exercise
the same full-resolution allocation class that escaped the normal 1400x720 smoke.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import cv2
import numpy as np

from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
from neyrobot_prod import selfie_v263_dense_identity_lock as v263
from neyrobot_prod import selfie_v263_diagnostics as diag
from neyrobot_prod.selfie_v263_runtime_safety import install as install_runtime_safety

WIDTH = 1856
HEIGHT = 2304


def _read(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"could not read public fixture: {path}")
    return image


def _two_person_fullsize(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    half = WIDTH // 2
    canvas = np.full((HEIGHT, WIDTH, 3), 128, dtype=np.uint8)
    for image, x0 in ((left, 0), (right, half)):
        scale = min((half * 0.90) / image.shape[1], (HEIGHT * 0.82) / image.shape[0])
        size = (max(96, int(round(image.shape[1] * scale))), max(96, int(round(image.shape[0] * scale))))
        resized = cv2.resize(image, size, interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LANCZOS4)
        y0 = max(0, (HEIGHT - resized.shape[0]) // 2)
        px = x0 + max(0, (half - resized.shape[1]) // 2)
        canvas[y0:y0 + resized.shape[0], px:px + resized.shape[1]] = resized
    return canvas


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

    male = _read(args.fixtures / "verify_now_2024.jpg")
    female = _read(args.fixtures / "verify_curie.jpg")
    stage1 = _two_person_fullsize(male, female)
    if stage1.shape[:2] != (HEIGHT, WIDTH):
        raise RuntimeError(f"production-size fixture wrong shape: {stage1.shape}")

    ok_src, src_png = cv2.imencode(".png", male, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    ok_stage, stage_png = cv2.imencode(".png", stage1, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    if not ok_src or not ok_stage:
        raise RuntimeError("public fixture PNG encoding failed")

    yunet, dense_model, recognition_model = asyncio.run(_models())
    rss_before, peak_before = diag.memory_snapshot()
    output, metrics, _ = v263._transfer_attempt(
        bytes(stage_png), bytes(src_png), yunet, dense_model, recognition_model, strict=False
    )
    rss_after, peak_after = diag.memory_snapshot()

    final = v253._decode_bgr(output)
    firewall_x = max(256, min(WIDTH, int(round(WIDTH * 0.55))))
    person_b_untouched = bool(np.array_equal(final[:, firewall_x:], stage1[:, firewall_x:]))
    gate_passed, failures = v263._quality_gate(metrics)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)

    result = {
        "width": WIDTH,
        "height": HEIGHT,
        "pixels": WIDTH * HEIGHT,
        "output_png": output.startswith(b"\x89PNG\r\n\x1a\n"),
        "output_bytes": len(output),
        "person_b_untouched": person_b_untouched,
        "quality_gate_reached": True,
        "quality_gate_passed": gate_passed,
        "quality_failures": failures,
        "rss_before_bytes": rss_before,
        "rss_after_bytes": rss_after,
        "peak_before_bytes": peak_before,
        "peak_after_bytes": peak_after,
        "peak_delta_bytes": max(0, peak_after - peak_before),
        "metrics": {k: round(float(v), 6) for k, v in metrics.items()},
    }
    print("V263_PRODUCTION_SIZE_RESULT " + json.dumps(result, sort_keys=True), flush=True)
    if not person_b_untouched:
        raise SystemExit("V263 production-size PERSON-B pixel lock failed")
    if not result["output_png"]:
        raise SystemExit("V263 production-size output is not PNG")


if __name__ == "__main__":
    main()
