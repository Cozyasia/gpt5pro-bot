# -*- coding: utf-8 -*-
"""Temporary one-shot production V263 validation; removed after rollout check."""
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

VERSION = "v263-production-selftest-once-2026-08-28"
_SENTINEL = Path("/data/celebrity_selfie/.v263_production_selftest_once_20260828.done")
_ARTIFACT_DIR = Path("/data/celebrity_selfie/v263_production_selftest_20260828")
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


def _preview_webp(raw: bytes, *, max_side: int = 700, quality: int = 80) -> bytes:
    from PIL import Image
    with Image.open(io.BytesIO(bytes(raw))) as source:
        im = source.convert("RGB")
        im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, format="WEBP", quality=quality, method=4)
        return out.getvalue()


def _face_crop_webp(raw: bytes, bbox: tuple[float, float, float, float]) -> bytes:
    from PIL import Image
    with Image.open(io.BytesIO(bytes(raw))) as source:
        im = source.convert("RGB")
        w, h = im.size
        x, y, fw, fh = [float(v) for v in bbox]
        x0 = max(0, int(round(x - fw * 0.36)))
        x1 = min(w, int(round(x + fw * 1.36)))
        y0 = max(0, int(round(y - fh * 0.42)))
        y1 = min(h, int(round(y + fh * 1.34)))
        crop = im.crop((x0, y0, x1, y1))
        crop.thumbnail((640, 640), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        crop.save(out, format="WEBP", quality=86, method=4)
        return out.getvalue()


def _emit_artifact(name: str, raw: bytes) -> None:
    encoded = base64.b64encode(bytes(raw)).decode("ascii")
    chunk = 1800
    total = max(1, (len(encoded) + chunk - 1) // chunk)
    _log(f"ARTIFACT_BEGIN name={name} encoding=base64 bytes={len(raw)} parts={total}")
    for index in range(total):
        data = encoded[index * chunk:(index + 1) * chunk]
        _log(f"ARTIFACT name={name} part={index + 1}/{total} data={data}")
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
        self.filename = ""

    async def reply_document(self, *, document: Any, caption: str = "", **kwargs: Any) -> None:
        self.document_calls += 1
        self.filename = str(getattr(document, "filename", "") or "")

    async def reply_photo(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("lossless V263 delivery unexpectedly used photo mode")


async def _wait_until_ready() -> Any:
    """Wait for the actual transfer owner, not stale compatibility version markers."""
    deadline = time.monotonic() + 120.0
    last = "V263 module/owner not ready"
    while time.monotonic() < deadline:
        runtime = _runtime()
        try:
            from neyrobot_prod import selfie_v263_dense_identity_lock as v263
            active = v263._modules()[8]._true_face_transfer
            if runtime is not None and bool(getattr(v263, "_INSTALLED", False)) and active is v263._true_face_transfer_v263:
                return runtime
            last = (
                f"runtime={'yes' if runtime is not None else 'no'} "
                f"installed={bool(getattr(v263, '_INSTALLED', False))} "
                f"owner={'v263' if active is v263._true_face_transfer_v263 else 'other'}"
            )
        except Exception as exc:
            last = f"{type(exc).__name__}:{str(exc)[:180]}"
        await asyncio.sleep(2.0)
    raise RuntimeError(f"V263 production runtime did not become ready: {last}")


def _metric_text(metrics: dict[str, float]) -> str:
    return (
        "identity_similarity_cosine=%.6f left_eye_error=%.6f right_eye_error=%.6f "
        "interocular_ratio_delta=%.6f nose_mouth_axis_delta=%.6f inner_face_landmark_nme=%.6f "
        "eye_asymmetry_delta=%.6f"
        % (
            float(metrics["identity_similarity_cosine"]),
            float(metrics["left_eye_error"]),
            float(metrics["right_eye_error"]),
            float(metrics["interocular_ratio_delta"]),
            float(metrics["nose_mouth_axis_delta"]),
            float(metrics["inner_face_landmark_nme"]),
            float(metrics["eye_asymmetry_delta"]),
        )
    )


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

    v263.enforce_runtime(bind_generate=True)
    if v263._modules()[8]._true_face_transfer is not v263._true_face_transfer_v263:
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
    _, hero_refs = v229._identity_refs([source, source, source], slug)
    if len(hero_refs) != 3:
        raise RuntimeError(f"expected 3 prepared hero refs, got {len(hero_refs)}")

    scene = "an elegant private restaurant with warm realistic lighting, natural front-camera selfie"
    prompt = transfer._stage1_prompt(hero_name, scene, "Селфи", False, 3)
    refs: list[tuple[str, bytes]] = [
        ("USER SOURCE PHOTO #3 — PERSON A ONLY: pose/expression/body; NEVER apply to PERSON B", source),
    ]
    refs.extend(hero_refs)

    _log(
        "START route=production_gemini_plus_v262_v263 source=public_fixture "
        f"hero_slug={slug} hero_name={json.dumps(hero_name, ensure_ascii=False)} refs=4 billing=false"
    )
    stage1, model = await v229._call_google(prompt, refs, "composition_identity_separated")
    sw, sh = _dims(stage1)
    _log(f"STAGE1 status=success model={model} dims={sw}x{sh} bytes={len(stage1)} sha12={_sha12(stage1)}")

    # Exactly one production comparison: same Stage-1 scene and authoritative source.
    v262_output, v262_provider = await v262._true_face_transfer_v262(runtime, stage1, source, 3)
    v263_output, v263_provider = await v263._true_face_transfer_v263(runtime, stage1, source, 3)

    path = str(getattr(runtime, "AI_SELFIE_LAST_IDENTITY_PATH", "") or "")
    strict_triggered = path == "strict"

    import numpy as np
    yunet_path = await v253._ensure_yunet_model()
    dense_path, recognition_path = await v263._ensure_identity_models()
    stage_bgr = v253._decode_bgr(stage1)
    source_bgr = v253._decode_bgr(source)
    v262_bgr = v253._decode_bgr(v262_output)
    v263_bgr = v253._decode_bgr(v263_output)
    h, w = stage_bgr.shape[:2]
    firewall_x = max(256, min(w, int(round(w * 0.55))))
    if v262_bgr.shape != stage_bgr.shape or v263_bgr.shape != stage_bgr.shape:
        raise RuntimeError("V262/V263 changed production scene dimensions")

    person_b_v262_untouched = bool(np.array_equal(stage_bgr[:, firewall_x:], v262_bgr[:, firewall_x:]))
    person_b_v263_untouched = bool(np.array_equal(stage_bgr[:, firewall_x:], v263_bgr[:, firewall_x:]))

    source_bbox, source_pts5 = v253._yunet_face(source_bgr, yunet_path, label="prod_selftest_source")
    target_bbox, target_pts5 = v253._yunet_face(stage_bgr[:, :firewall_x], yunet_path, label="prod_selftest_target")
    v262_bbox, _ = v253._yunet_face(v262_bgr[:, :firewall_x], yunet_path, label="prod_selftest_v262")
    v263_bbox, _ = v253._yunet_face(v263_bgr[:, :firewall_x], yunet_path, label="prod_selftest_v263")

    matrix, _ = v263._similarity_transform(source_pts5, target_pts5)
    source_dense = v263._dense_landmarks_68(source_bgr, source_bbox, dense_path, label="prod_source")
    target_dense = v263._dense_landmarks_68(stage_bgr, target_bbox, dense_path, label="prod_target")
    projected_dense = v262._project_points(matrix, source_dense)
    face_min = min(float(target_bbox[2]), float(target_bbox[3]))
    desired_dense = v263._desired_identity_geometry(projected_dense, target_dense, face_min, strict=strict_triggered)
    v262_dense = v263._dense_landmarks_68(v262_bgr, v262_bbox, dense_path, label="prod_v262")
    v263_dense = v263._dense_landmarks_68(v263_bgr, v263_bbox, dense_path, label="prod_v263")

    source_embedding = v263._mobileface_embedding(source_bgr, source_dense, recognition_path)
    v262_embedding = v263._mobileface_embedding(v262_bgr, v262_dense, recognition_path)
    v263_embedding = v263._mobileface_embedding(v263_bgr, v263_dense, recognition_path)
    v262_metrics = v263._quality_metrics(source_embedding, v262_embedding, desired_dense, v262_dense)
    v263_metrics = v263._quality_metrics(source_embedding, v263_embedding, desired_dense, v263_dense)
    v262_gate, v262_failures = v263._quality_gate(v262_metrics)
    v263_gate, v263_failures = v263._quality_gate(v263_metrics)
    strict_success = strict_triggered and v263_gate

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
    v262_scene = _preview_webp(v262_output, max_side=760, quality=82)
    v263_scene = _preview_webp(v263_output, max_side=760, quality=82)

    _log(
        "V262_METRICS geometry_mode=unified_all5_landmark_field landmarks=5 "
        + _metric_text(v262_metrics)
        + f" quality_if_v263_gate={'pass' if v262_gate else 'fail'} failures={'none' if not v262_failures else '|'.join(v262_failures)}"
    )
    _log(
        "V263_METRICS geometry_mode=pipnet_68 landmarks=68 "
        + _metric_text(v263_metrics)
        + f" quality_gate={'pass' if v263_gate else 'fail'} failures={'none' if not v263_failures else '|'.join(v263_failures)}"
    )
    _log(
        "RESULT status=%s strict_retry_triggered=%s strict_retry_success=%s "
        "person_b_v262_untouched=%s person_b_v263_untouched=%s no_neck=true independent_eye_patch=false "
        "png=%s original_document_delivery=%s v262_provider=%s v263_provider=%s "
        "source_sha12=%s v262_sha12=%s v263_sha12=%s"
        % (
            "pass" if v263_gate else "fail",
            str(strict_triggered).lower(), str(strict_success).lower(),
            str(person_b_v262_untouched).lower(), str(person_b_v263_untouched).lower(),
            str(_png(v263_output)).lower(), str(delivery_ok).lower(),
            v262_provider, v263_provider, _sha12(source), _sha12(v262_output), _sha12(v263_output),
        )
    )

    _emit_artifact("source_face.webp", source_face)
    _emit_artifact("v262_face.webp", v262_face)
    _emit_artifact("v263_face.webp", v263_face)
    _emit_artifact("v262_scene.webp", v262_scene)
    _emit_artifact("v263_scene.webp", v263_scene)

    _SENTINEL.parent.mkdir(parents=True, exist_ok=True)
    _SENTINEL.write_text(
        json.dumps({
            "version": VERSION,
            "hero": slug,
            "model": model,
            "quality_path": path,
            "v262_metrics": v262_metrics,
            "v263_metrics": v263_metrics,
            "v263_gate": v263_gate,
            "strict_retry_triggered": strict_triggered,
            "strict_retry_success": strict_success,
            "person_b_v263_untouched": person_b_v263_untouched,
            "document_delivery": delivery_ok,
        }, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    _log("COMPLETE sentinel_written=true")

    if not v263_gate:
        raise RuntimeError("production V263 identity quality gate failed")
    if not person_b_v263_untouched:
        raise RuntimeError("production PERSON-B firewall verification failed")
    if not delivery_ok:
        raise RuntimeError("production PNG/document delivery verification failed")


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
    threading.Thread(target=_thread_main, name="v263-production-selftest-once", daemon=True).start()
    _log("ARMED bounded_wait=120s billing=false source=public_fixture")


__all__ = ["VERSION", "install_async"]
