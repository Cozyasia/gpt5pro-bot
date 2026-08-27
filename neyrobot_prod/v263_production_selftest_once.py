# -*- coding: utf-8 -*-
"""One-shot production-only V263 verification.

Temporary rollout diagnostic. It uses a public portrait fixture, production Gemini
credentials, and the first already-prepared celebrity from persistent /data.
No Telegram user data is read, no payment runner is called, and no secret value is
logged. The module is removed immediately after the verification deploy.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import threading
import time
from pathlib import Path
from typing import Any

VERSION = "v263-production-selftest-once-2026-08-27"
_SENTINEL = Path("/data/celebrity_selfie/.v263_production_selftest_once_20260827.done")
_ARTIFACT_DIR = Path("/data/celebrity_selfie/v263_production_selftest_20260827")
_SOURCE_URL = (
    "https://raw.githubusercontent.com/yakhyo/uniface/"
    "df87c6531f4d1bdad665882d42d658590e724ea4/assets/source/verify_now_2024.jpg"
)
_STARTED = False


def _log(message: str) -> None:
    print(f"AI_SELFIE_V263_PROD_SELFTEST {message}", flush=True)


def _runtime() -> Any | None:
    from neyrobot_prod import selfie_v241_authoritative_runtime as v241
    return v241._runtime()


def _png(raw: bytes) -> bool:
    return bytes(raw or b"").startswith(b"\x89PNG\r\n\x1a\n")


def _dims(raw: bytes) -> tuple[int, int]:
    from PIL import Image
    with Image.open(io.BytesIO(bytes(raw))) as im:
        return int(im.width), int(im.height)


def _sha12(raw: bytes) -> str:
    return hashlib.sha256(bytes(raw or b"")).hexdigest()[:12]


def _preview_webp(raw: bytes, *, max_side: int = 700, quality: int = 78) -> bytes:
    from PIL import Image
    with Image.open(io.BytesIO(bytes(raw))) as source:
        im = source.convert("RGB")
        im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, format="WEBP", quality=quality, method=4)
        return out.getvalue()


def _face_crop_webp(raw: bytes, bbox: tuple[float, float, float, float], *, max_side: int = 640) -> bytes:
    from PIL import Image
    with Image.open(io.BytesIO(bytes(raw))) as source:
        im = source.convert("RGB")
        w, h = im.size
        x, y, fw, fh = [float(v) for v in bbox]
        pad_x = fw * 0.36
        pad_top = fh * 0.42
        pad_bottom = fh * 0.34
        x0 = max(0, int(round(x - pad_x)))
        x1 = min(w, int(round(x + fw + pad_x)))
        y0 = max(0, int(round(y - pad_top)))
        y1 = min(h, int(round(y + fh + pad_bottom)))
        crop = im.crop((x0, y0, x1, y1))
        crop.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        crop.save(out, format="WEBP", quality=84, method=4)
        return out.getvalue()


def _emit_artifact(name: str, raw: bytes) -> None:
    encoded = base64.b64encode(bytes(raw)).decode("ascii")
    chunk = 1800
    total = max(1, (len(encoded) + chunk - 1) // chunk)
    _log(f"ARTIFACT_BEGIN name={name} encoding=base64 bytes={len(raw)} parts={total}")
    for index in range(total):
        part = encoded[index * chunk:(index + 1) * chunk]
        _log(f"ARTIFACT name={name} part={index + 1}/{total} data={part}")
    _log(f"ARTIFACT_END name={name} sha12={_sha12(raw)}")


async def _download_source() -> bytes:
    import httpx
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=20.0), follow_redirects=True) as client:
        response = await client.get(_SOURCE_URL)
        response.raise_for_status()
        raw = bytes(response.content or b"")
    if len(raw) < 10_000:
        raise RuntimeError(f"public source fixture unexpectedly small: {len(raw)}")
    return raw


class _FakeMessage:
    def __init__(self) -> None:
        self.document_calls = 0
        self.last_filename = ""

    async def reply_document(self, *, document: Any, caption: str = "", **kwargs: Any) -> None:
        self.document_calls += 1
        self.last_filename = str(getattr(document, "filename", "") or "")

    async def reply_photo(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("lossless V263 delivery unexpectedly used photo mode")


async def _wait_until_ready() -> Any:
    deadline = time.monotonic() + 120.0
    last = "runtime unavailable"
    while time.monotonic() < deadline:
        runtime = _runtime()
        if runtime is not None:
            version = str(getattr(runtime, "AI_SELFIE_RUNTIME_VERSION", "") or "")
            if version.startswith("v263-dense-identity-lock"):
                return runtime
            last = f"runtime version={version or 'unset'}"
        await asyncio.sleep(2.0)
    raise RuntimeError(f"V263 production runtime did not become ready: {last}")


async def _run() -> None:
    if _SENTINEL.exists():
        _log("SKIP reason=sentinel_exists")
        return

    runtime = await _wait_until_ready()
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer
    from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
    from neyrobot_prod import selfie_v262_landmark_field_compositor as v262
    from neyrobot_prod import selfie_v263_dense_identity_lock as v263

    # Reassert final ownership immediately before the test, then verify it stayed active.
    v263.enforce_runtime(bind_generate=True)
    modules = v263._modules()
    active_transfer = modules[8]._true_face_transfer
    if active_transfer is not v263._true_face_transfer_v263:
        raise RuntimeError("V263 is not the active PERSON-A transfer owner")

    ready: list[tuple[str, dict[str, Any]]] = []
    for slug, meta in base.CHARACTERS.items():
        try:
            if base._character_ready(runtime, slug):
                ready.append((str(slug), dict(meta)))
        except Exception:
            continue
    if not ready:
        raise RuntimeError("no prepared production celebrity is available in persistent storage")
    slug, meta = ready[0]
    hero_name = str(meta.get("name") or slug).replace("\n", " ")[:120]

    source = await _download_source()
    user_photos = [source, source, source]
    _, hero_refs = v229._identity_refs(user_photos, slug)
    if len(hero_refs) != 3:
        raise RuntimeError(f"expected 3 prepared hero refs, got {len(hero_refs)}")

    scene = "an elegant private restaurant with warm realistic lighting, natural front-camera selfie"
    prompt = transfer._stage1_prompt(hero_name, scene, "Селфи", False, 3)
    stage1_refs: list[tuple[str, bytes]] = [
        ("USER SOURCE PHOTO #3 — PERSON A ONLY: pose/expression/body; NEVER apply to PERSON B", source),
    ]
    stage1_refs.extend(hero_refs)

    _log(
        "START route=production_gemini_plus_v262_v263 source=public_fixture "
        f"hero_slug={slug} hero_name={json.dumps(hero_name, ensure_ascii=False)} refs=4 billing=false"
    )
    stage1, model = await v229._call_google(prompt, stage1_refs, "composition_identity_separated")
    _log(
        f"STAGE1 status=success model={model} dims={_dims(stage1)[0]}x{_dims(stage1)[1]} "
        f"bytes={len(stage1)} sha12={_sha12(stage1)}"
    )

    # Same generated scene and same authoritative source are fed to V262 and V263.
    v262_output, v262_provider = await v262._true_face_transfer_v262(runtime, stage1, source, 3)
    v263_output, v263_provider = await v263._true_face_transfer_v263(runtime, stage1, source, 3)

    metrics = dict(getattr(runtime, "AI_SELFIE_LAST_IDENTITY_METRICS", {}) or {})
    path = str(getattr(runtime, "AI_SELFIE_LAST_IDENTITY_PATH", "") or "")
    passed, failures = v263._quality_gate(metrics)
    strict_triggered = path == "strict"
    strict_success = strict_triggered and passed

    import cv2
    import numpy as np
    yunet_path = await v253._ensure_yunet_model()
    stage_bgr = v253._decode_bgr(stage1)
    v262_bgr = v253._decode_bgr(v262_output)
    v263_bgr = v253._decode_bgr(v263_output)
    source_bgr = v253._decode_bgr(source)
    h, w = stage_bgr.shape[:2]
    firewall_x = max(256, min(w, int(round(w * 0.55))))
    if v262_bgr.shape != stage_bgr.shape or v263_bgr.shape != stage_bgr.shape:
        raise RuntimeError("V262/V263 changed production scene dimensions")
    person_b_v262_untouched = bool(np.array_equal(stage_bgr[:, firewall_x:], v262_bgr[:, firewall_x:]))
    person_b_v263_untouched = bool(np.array_equal(stage_bgr[:, firewall_x:], v263_bgr[:, firewall_x:]))

    source_bbox, _ = v253._yunet_face(source_bgr, yunet_path, label="prod_selftest_source")
    v262_bbox, _ = v253._yunet_face(v262_bgr[:, :firewall_x], yunet_path, label="prod_selftest_v262")
    v263_bbox, _ = v253._yunet_face(v263_bgr[:, :firewall_x], yunet_path, label="prod_selftest_v263")

    fake = _FakeMessage()
    delivered = await v253._deliver_original(fake, v263_output, "V263 production selftest", prefer_document=True)
    delivery_ok = bool(fake.document_calls == 1 and delivered == v263_output and _png(v263_output))

    _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (_ARTIFACT_DIR / "source.jpg").write_bytes(source)
    (_ARTIFACT_DIR / "stage1.bin").write_bytes(stage1)
    (_ARTIFACT_DIR / "v262.png").write_bytes(v262_output)
    (_ARTIFACT_DIR / "v263.png").write_bytes(v263_output)

    source_face = _face_crop_webp(source, tuple(float(x) for x in source_bbox))
    v262_face = _face_crop_webp(v262_output, tuple(float(x) for x in v262_bbox))
    v263_face = _face_crop_webp(v263_output, tuple(float(x) for x in v263_bbox))
    scene_preview = _preview_webp(v263_output, max_side=760, quality=82)

    _log(
        "RESULT status=%s geometry_mode=pipnet_68 landmarks=68 "
        "identity_similarity_cosine=%.6f left_eye_error=%.6f right_eye_error=%.6f "
        "interocular_ratio_delta=%.6f nose_mouth_axis_delta=%.6f inner_face_landmark_nme=%.6f "
        "eye_asymmetry_delta=%.6f strict_retry_triggered=%s strict_retry_success=%s quality_failures=%s "
        "person_b_v262_untouched=%s person_b_v263_untouched=%s png=%s document_delivery=%s "
        "v262_provider=%s v263_provider=%s source_sha12=%s v262_sha12=%s v263_sha12=%s"
        % (
            "pass" if passed else "fail",
            float(metrics.get("identity_similarity_cosine", float("nan"))),
            float(metrics.get("left_eye_error", float("nan"))),
            float(metrics.get("right_eye_error", float("nan"))),
            float(metrics.get("interocular_ratio_delta", float("nan"))),
            float(metrics.get("nose_mouth_axis_delta", float("nan"))),
            float(metrics.get("inner_face_landmark_nme", float("nan"))),
            float(metrics.get("eye_asymmetry_delta", float("nan"))),
            str(strict_triggered).lower(), str(strict_success).lower(),
            "none" if not failures else "|".join(failures),
            str(person_b_v262_untouched).lower(), str(person_b_v263_untouched).lower(),
            str(_png(v263_output)).lower(), str(delivery_ok).lower(),
            v262_provider, v263_provider, _sha12(source), _sha12(v262_output), _sha12(v263_output),
        )
    )

    _emit_artifact("source_face.webp", source_face)
    _emit_artifact("v262_face.webp", v262_face)
    _emit_artifact("v263_face.webp", v263_face)
    _emit_artifact("v263_scene.webp", scene_preview)

    if not passed:
        raise RuntimeError("production V263 identity quality gate failed")
    if not person_b_v263_untouched:
        raise RuntimeError("production PERSON-B firewall verification failed")
    if not delivery_ok:
        raise RuntimeError("production PNG/document delivery verification failed")

    _SENTINEL.parent.mkdir(parents=True, exist_ok=True)
    _SENTINEL.write_text(
        json.dumps({
            "version": VERSION,
            "hero": slug,
            "model": model,
            "quality_path": path,
            "metrics": metrics,
            "v262_sha12": _sha12(v262_output),
            "v263_sha12": _sha12(v263_output),
        }, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    _log("COMPLETE status=pass sentinel_written=true")


def _thread_main() -> None:
    try:
        asyncio.run(_run())
    except Exception as exc:
        _log(f"FAILED error={type(exc).__name__}:{str(exc)[:1200]}")


def install_async() -> None:
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    thread = threading.Thread(target=_thread_main, name="v263-production-selftest-once", daemon=True)
    thread.start()
    _log("ARMED bounded_wait=120s billing=false source=public_fixture")


__all__ = ["VERSION", "install_async"]
