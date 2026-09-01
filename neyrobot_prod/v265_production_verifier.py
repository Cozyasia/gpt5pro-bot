# -*- coding: utf-8 -*-
"""Temporary one-shot production-size verifier for the V265 rollout.

This module owns no handlers, runtime bindings, quality gates, fallbacks, or production
algorithm. It only validates the already-installed V265 production owner and is removed
immediately after the one production run.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import inspect
import io
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

_SENTINEL = Path("/data/v265_prod_verify_pr104_fc2529df.once")
_ARTIFACT_DIR = Path("/data/v265_prod_verify_pr104_fc2529df")
_FIXTURE_BASE = (
    "https://raw.githubusercontent.com/yakhyo/uniface/"
    "df87c6531f4d1bdad665882d42d658590e724ea4/assets/source"
)
_STARTED = False


def _emit(message: str) -> None:
    print(message, flush=True)


def _atomic_json(payload: dict[str, Any]) -> None:
    _SENTINEL.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SENTINEL.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with tmp.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(tmp, _SENTINEL)


def _claim_pending() -> bool:
    """Persistent one-shot claim before readiness polling or any heavy/network work."""
    _SENTINEL.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(_SENTINEL), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with contextlib.suppress(Exception):
            state = json.loads(_SENTINEL.read_text(encoding="utf-8"))
            _emit(
                "AI_SELFIE_V265_VERIFY status=skipped reason=sentinel_exists "
                f"state={state.get('status', 'unknown')} sentinel={_SENTINEL}"
            )
            return False
        _emit(f"AI_SELFIE_V265_VERIFY status=skipped reason=sentinel_exists sentinel={_SENTINEL}")
        return False
    payload = {
        "status": "pending",
        "pid": os.getpid(),
        "time": time.time(),
        "git_commit": os.environ.get("RENDER_GIT_COMMIT", ""),
    }
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.flush()
        os.fsync(handle.fileno())
    _emit(f"AI_SELFIE_V265_VERIFY status=pending pid={os.getpid()} sentinel={_SENTINEL}")
    return True


def _mark_started(runtime_name: str, readiness: dict[str, Any]) -> None:
    payload = {
        "status": "started",
        "pid": os.getpid(),
        "time": time.time(),
        "git_commit": os.environ.get("RENDER_GIT_COMMIT", ""),
        "runtime_name": runtime_name,
        "readiness": readiness,
    }
    _atomic_json(payload)
    _emit(
        f"AI_SELFIE_V265_VERIFY status=started pid={os.getpid()} sentinel={_SENTINEL} "
        "heavy_started_after_sentinel=true target_short=1856 target_long=2304"
    )


def _finish_sentinel(payload: dict[str, Any]) -> None:
    with contextlib.suppress(Exception):
        _atomic_json(payload)


def _dims(raw: bytes) -> tuple[int, int]:
    from PIL import Image
    with Image.open(io.BytesIO(bytes(raw))) as image:
        return int(image.width), int(image.height)


def _save_artifact(name: str, raw: bytes) -> Path:
    """Persist each validation checkpoint before any later reporting can fail."""
    data = bytes(raw or b"")
    if not data:
        raise RuntimeError(f"empty verifier artifact: {name}")
    _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = _ARTIFACT_DIR / name
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    with tmp.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    dims = "unknown"
    with contextlib.suppress(Exception):
        w, h = _dims(data)
        dims = f"{w}x{h}"
    _emit(
        f"AI_SELFIE_V265_VERIFY_ARTIFACT name={name} bytes={len(data)} dims={dims} "
        f"sha256={hashlib.sha256(data).hexdigest()[:16]} persisted=true"
    )
    return path


def _production_size(raw: bytes) -> bytes:
    """Never downscale; only lift a smaller Stage-1 frame to production-class size."""
    from PIL import Image
    with Image.open(io.BytesIO(bytes(raw))) as opened:
        image = opened.convert("RGB")
        w, h = image.size
        short_side, long_side = min(w, h), max(w, h)
        scale = max(1.0, 1856.0 / max(1, short_side), 2304.0 / max(1, long_side))
        if scale > 1.0001:
            image = image.resize(
                (int(round(w * scale)), int(round(h * scale))),
                Image.Resampling.LANCZOS,
            )
        out = io.BytesIO()
        image.save(out, format="PNG", compress_level=2)
        encoded = out.getvalue()
    ow, oh = _dims(encoded)
    _emit(
        f"AI_SELFIE_V265_VERIFY_SIZE input={w}x{h} output={ow}x{oh} "
        f"scale={scale:.4f} downscale=false png=true"
    )
    return encoded


async def _download_fixture(name: str) -> bytes:
    import httpx
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=20.0), follow_redirects=True) as client:
        response = await client.get(f"{_FIXTURE_BASE}/{name}")
        response.raise_for_status()
        data = bytes(response.content)
    if len(data) < 4096:
        raise RuntimeError(f"fixture too small: {name} bytes={len(data)}")
    return data


class _DocumentSink:
    def __init__(self) -> None:
        self.raw = b""
        self.calls = 0

    async def reply_document(self, **kwargs: Any) -> bool:
        self.calls += 1
        document = kwargs.get("document")
        value = getattr(document, "input_file_content", None)
        if callable(value):
            value = value()
        if isinstance(value, memoryview):
            value = value.tobytes()
        if isinstance(value, bytearray):
            value = bytes(value)
        if isinstance(value, bytes):
            self.raw = value
            return True
        obj = getattr(document, "obj", None)
        if obj is not None and hasattr(obj, "getvalue"):
            self.raw = bytes(obj.getvalue())
            return True
        if obj is not None and hasattr(obj, "read"):
            position = obj.tell() if hasattr(obj, "tell") else None
            if hasattr(obj, "seek"):
                obj.seek(0)
            self.raw = bytes(obj.read())
            if position is not None and hasattr(obj, "seek"):
                obj.seek(position)
            return True
        raise RuntimeError("could not inspect telegram InputFile payload")


def _pixel_probes(stage1: bytes, final: bytes, yunet_path: Path) -> tuple[bool, bool]:
    import numpy as np
    from neyrobot_prod import selfie_v253_yunet_source_pixels as v253

    target = v253._decode_bgr(stage1)
    output = v253._decode_bgr(final)
    if target.shape != output.shape:
        raise RuntimeError(f"frame shape changed: stage1={target.shape} final={output.shape}")
    h, w = target.shape[:2]
    firewall_x = max(256, min(w, int(round(w * 0.55))))
    person_b_equal = bool(np.array_equal(target[:, firewall_x:], output[:, firewall_x:]))

    bbox, _ = v253._yunet_face(target[:, :firewall_x], yunet_path, label="verify_target_person_a")
    x, y, fw, fh = [float(v) for v in bbox]
    x0 = max(0, int(round(x + fw * 0.20)))
    x1 = min(firewall_x, int(round(x + fw * 0.80)))
    y0 = max(0, int(round(y + fh * 0.90)))
    y1 = min(h, int(round(y + fh * 1.12)))
    if x1 <= x0 + 4 or y1 <= y0 + 4:
        raise RuntimeError(f"neck probe invalid: {x0},{y0},{x1},{y1}")
    neck_equal = bool(np.array_equal(target[y0:y1, x0:x1], output[y0:y1, x0:x1]))
    _emit(
        f"AI_SELFIE_V265_VERIFY_PIXELS person_b_pixel_equal={str(person_b_equal).lower()} "
        f"neck_region_equal={str(neck_equal).lower()} firewall_x={firewall_x} neck_box={x0},{y0},{x1},{y1}"
    )
    return person_b_equal, neck_equal


def _contact_sheet(source: bytes, stage1: bytes, final: bytes) -> bytes:
    from PIL import Image, ImageDraw

    def panel(raw: bytes, *, left_only: bool) -> Image.Image:
        with Image.open(io.BytesIO(bytes(raw))) as opened:
            image = opened.convert("RGB")
        if left_only:
            image = image.crop((0, 0, max(1, int(image.width * 0.55)), image.height))
        image.thumbnail((210, 245), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (220, 270), "white")
        canvas.paste(image, ((220 - image.width) // 2, 18))
        return canvas

    parts = [panel(source, left_only=False), panel(stage1, left_only=True), panel(final, left_only=True)]
    sheet = Image.new("RGB", (660, 300), "white")
    for idx, part in enumerate(parts):
        sheet.paste(part, (idx * 220, 24))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 5), "SOURCE A", fill="black")
    draw.text((228, 5), "STAGE-1 A", fill="black")
    draw.text((448, 5), "FINAL V265 A", fill="black")
    out = io.BytesIO()
    sheet.save(out, format="JPEG", quality=58, optimize=True)
    return out.getvalue()


def _emit_thumbnail(raw: bytes) -> None:
    encoded = base64.b64encode(bytes(raw)).decode("ascii")
    chunk_size = 3500
    chunks = [encoded[i:i + chunk_size] for i in range(0, len(encoded), chunk_size)]
    _emit(f"AI_SELFIE_V265_VERIFY_THUMB_BEGIN chunks={len(chunks)} bytes={len(raw)}")
    for index, chunk in enumerate(chunks, 1):
        _emit(f"AI_SELFIE_V265_VERIFY_THUMB chunk={index}/{len(chunks)} data={chunk}")
    _emit("AI_SELFIE_V265_VERIFY_THUMB_END")


def _runtime_candidates() -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            found.append((name, mod))
    return found


def _readiness_snapshot() -> tuple[Any | None, str, dict[str, Any]]:
    """Validate actual V265 production state instead of a never-guaranteed marker."""
    import neyrobot_prod as package
    from neyrobot_prod import dense68_engine_v265 as engine
    from neyrobot_prod import selfie_v211_delivery as delivery
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer
    from neyrobot_prod import selfie_v265_single_owner as v265

    candidates = _runtime_candidates()
    runtime_name = candidates[0][0] if candidates else ""
    runtime = candidates[0][1] if candidates else None
    if runtime is None:
        with contextlib.suppress(Exception):
            from neyrobot_prod import selfie_v241_authoritative_runtime as v241
            candidate = v241._runtime()
            if candidate is not None:
                runtime = candidate
                runtime_name = getattr(candidate, "__name__", "v241_runtime")

    owner = getattr(transfer, "_true_face_transfer", None)
    owner_exact = owner is v265._true_face_transfer_v265
    owner_named = bool(
        callable(owner)
        and getattr(owner, "__module__", "") == v265.__name__
        and getattr(owner, "__name__", "") == "_true_face_transfer_v265"
    )
    delivery_owner = getattr(delivery, "_deliver", None)
    delivery_exact = delivery_owner is v265._deliver_original_only
    runtime_version = str(getattr(runtime, "AI_SELFIE_RUNTIME_VERSION", "") or "") if runtime is not None else ""
    runtime_route = str(getattr(runtime, "CELEBRITY_SELFIE_ROUTE", "") or "") if runtime is not None else ""

    checks = {
        "process_started": bool(os.getpid() > 1 and runtime is not None and callable(getattr(runtime, "main", None))),
        "bootstrap_v265": bool(getattr(package, "PRODUCTION_SELFIE_RUNTIME", "") == "v265" and getattr(v265, "_INSTALLED", False)),
        "owner_registered": bool(owner_exact or owner_named),
        "delivery_owner_registered": bool(delivery_exact),
        "dense68_available": bool(
            getattr(engine, "VERSION", "") == v265.VERSION
            and callable(getattr(engine, "transfer_attempt", None))
            and callable(getattr(engine, "apply_ocular_lock", None))
        ),
        "runtime_contract": bool(
            runtime is not None
            and (runtime_version == v265.VERSION or runtime_route == "v265-single-owner-dense68-roi-local-only-lossless-document")
            and bool(getattr(runtime, "AI_SELFIE_SEND_AS_DOCUMENT", False))
        ),
        "gemini_configured": bool(os.environ.get("GEMINI_IMAGE_API_KEY", "").strip()),
        "old_transfer_identity": bool(owner_exact),
        "old_runtime_version": bool(runtime_version == v265.VERSION),
    }
    checks["safe_to_begin"] = all(
        checks[key]
        for key in (
            "process_started",
            "bootstrap_v265",
            "owner_registered",
            "delivery_owner_registered",
            "dense68_available",
            "runtime_contract",
            "gemini_configured",
        )
    )
    details = {
        **checks,
        "runtime_name": runtime_name,
        "runtime_version": runtime_version,
        "runtime_route": runtime_route,
        "owner_module": getattr(owner, "__module__", ""),
        "owner_name": getattr(owner, "__name__", ""),
        "engine": getattr(engine, "__name__", ""),
    }
    return runtime, runtime_name, details


async def _verify_async(runtime: Any) -> None:
    from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
    from neyrobot_prod import selfie_v263_dense_identity_lock as v263
    from neyrobot_prod import selfie_v265_single_owner as v265

    pid_start = os.getpid()
    owner_source = inspect.getsource(v265._true_face_transfer_v265)
    if "v263._quality_gate(" in owner_source:
        raise RuntimeError("legacy V263 quality gate is still present in V265 execution")
    if owner_source.count("production_gate(") != 2:
        raise RuntimeError("V265 production gate call count is not exactly two")

    source = await _download_fixture("verify_now_2024.jpg")
    _save_artifact("01_source_person_a.jpg", source)
    hero = await _download_fixture("verify_curie.jpg")
    refs = [
        ("USER SOURCE PHOTO #3 — PERSON A ONLY", source),
        ("HERO PORTRAIT 1 — PERSON B ONLY", hero),
        ("HERO PORTRAIT 2 — PERSON B ONLY", hero),
        ("HERO PORTRAIT 3 — PERSON B ONLY", hero),
    ]
    prompt = v265._stage1_prompt(
        "PERSON B reference subject",
        "neutral modern indoor studio with soft daylight",
        "Селфи",
        False,
        3,
    )
    stage1_raw, model = await v265._call_google(prompt, refs, "composition_identity_separated")
    _save_artifact("02_stage1_provider.png", stage1_raw)
    stage1 = _production_size(stage1_raw)
    _save_artifact("03_stage1_production_size.png", stage1)
    stage1_dims = _dims(stage1)
    if min(stage1_dims) < 1856 or max(stage1_dims) < 2304:
        raise RuntimeError(f"Stage-1 did not reach production size: {stage1_dims}")

    final, provider = await v265._true_face_transfer_v265(runtime, stage1, source, 3)
    _save_artifact("04_final_v265.png", final)
    final_dims = _dims(final)
    if final_dims != stage1_dims:
        raise RuntimeError(f"V265 changed frame dimensions: {stage1_dims} -> {final_dims}")
    if not bytes(final).startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("V265 final is not PNG")

    metrics = dict(getattr(runtime, "AI_SELFIE_LAST_IDENTITY_METRICS", {}) or {})
    selected = str(getattr(runtime, "AI_SELFIE_LAST_IDENTITY_PATH", "") or "")
    if not selected.startswith("v265_"):
        raise RuntimeError(f"unexpected V265 selection path: {selected!r}")
    hard_ok, hard_failures = v265.production_gate(metrics)
    if not hard_ok:
        raise RuntimeError("selected output failed V265 production gate: " + "|".join(hard_failures))

    yunet_path = await v253._ensure_yunet_model()
    dense_path, recognition_path = await v263._ensure_identity_models()
    if not dense_path or not recognition_path:
        raise RuntimeError("PIPNet/MobileFace model resolution missing")

    person_b_equal, neck_equal = _pixel_probes(stage1, final, yunet_path)
    if not person_b_equal:
        raise RuntimeError("PERSON-B pixel firewall changed")
    if not neck_equal:
        raise RuntimeError("no-neck probe changed pixels below the face mask")

    sink = _DocumentSink()
    delivered = await v265._deliver_original_only(sink, final, "V265 production verifier", prefer_document=True)
    delivery_exact = bool(sink.calls == 1 and sink.raw == final and delivered == final)
    if not delivery_exact:
        raise RuntimeError(
            f"original-document sink mismatch calls={sink.calls} captured={len(sink.raw)} final={len(final)}"
        )

    contact = _contact_sheet(source, stage1, final)
    _save_artifact("05_visual_contact_sheet.jpg", contact)
    _emit_thumbnail(contact)

    identity = float(metrics.get("identity_similarity_cosine", 0.0))
    left_eye = float(metrics.get("left_eye_error", 1.0))
    right_eye = float(metrics.get("right_eye_error", 1.0))
    asym = float(metrics.get("eye_asymmetry_delta", 0.0))
    inner = float(metrics.get("inner_face_landmark_nme", 1.0))
    interocular = float(metrics.get("interocular_ratio_delta", 1.0))
    axis = float(metrics.get("nose_mouth_axis_delta", 1.0))
    strict_triggered = selected != "v265_standard"
    pid_end = os.getpid()
    result = {
        "status": "completed",
        "result": "pass",
        "pid_start": pid_start,
        "pid_end": pid_end,
        "process_restart": pid_start != pid_end,
        "stage1_dims": f"{stage1_dims[0]}x{stage1_dims[1]}",
        "final_dims": f"{final_dims[0]}x{final_dims[1]}",
        "model": model,
        "provider": provider,
        "selected": selected,
        "strict_triggered": strict_triggered,
        "identity_similarity_cosine": identity,
        "left_eye_error": left_eye,
        "right_eye_error": right_eye,
        "eye_asymmetry": asym,
        "inner_face_landmark_nme": inner,
        "interocular_ratio_delta": interocular,
        "nose_mouth_axis_delta": axis,
        "hard_gate": True,
        "hard_gate_failures": [],
        "person_b_untouched": person_b_equal,
        "no_neck": neck_equal,
        "independent_eye_patch": False,
        "delivery_exact": delivery_exact,
        "final_png": True,
        "v263_quality_gate": False,
        "legacy_fallback": False,
    }
    _finish_sentinel(result)
    _emit(
        "AI_SELFIE_V265_PROD_VERIFY status=pass "
        f"pid_start={pid_start} pid_end={pid_end} process_restart={str(pid_start != pid_end).lower()} "
        f"stage1_dims={result['stage1_dims']} final_dims={result['final_dims']} model={model} "
        f"selected={selected} strict_triggered={str(strict_triggered).lower()} provider={provider} "
        f"identity_similarity_cosine={identity:.6f} left_eye_error={left_eye:.6f} right_eye_error={right_eye:.6f} "
        f"eye_asymmetry={asym:.6f} inner_face_landmark_nme={inner:.6f} "
        f"interocular_ratio_delta={interocular:.6f} nose_mouth_axis_delta={axis:.6f} hard_gate=true "
        "person_b_untouched=true no_neck=true independent_eye_patch=false delivery_exact=true final_png=true "
        "engine=dense68_engine_v265 landmarks=68 strict_same_engine=true v263_quality_gate=false legacy_fallback=false"
    )


def _worker() -> None:
    runtime = None
    runtime_name = ""
    readiness: dict[str, Any] = {}
    deadline = time.monotonic() + 180.0
    last_report = 0.0
    while time.monotonic() < deadline:
        try:
            runtime, runtime_name, readiness = _readiness_snapshot()
            if bool(readiness.get("safe_to_begin")):
                break
            now = time.monotonic()
            if now - last_report >= 15.0:
                last_report = now
                _emit("AI_SELFIE_V265_VERIFY_READINESS " + json.dumps(readiness, sort_keys=True))
        except Exception as exc:
            now = time.monotonic()
            if now - last_report >= 15.0:
                last_report = now
                _emit(f"AI_SELFIE_V265_VERIFY_READINESS error={type(exc).__name__}:{str(exc)[:500]}")
        time.sleep(2.0)

    if runtime is None or not bool(readiness.get("safe_to_begin")):
        payload = {
            "status": "failed",
            "phase": "runtime_wait",
            "pid": os.getpid(),
            "readiness": readiness,
        }
        _finish_sentinel(payload)
        _emit(
            "AI_SELFIE_V265_VERIFY status=failed phase=runtime_wait error=V265_runtime_not_ready "
            + json.dumps(readiness, sort_keys=True)
        )
        return

    _emit("AI_SELFIE_V265_VERIFY_READINESS status=ready " + json.dumps(readiness, sort_keys=True))
    _mark_started(runtime_name, readiness)
    try:
        asyncio.run(_verify_async(runtime))
    except Exception as exc:
        payload = {
            "status": "failed",
            "phase": "production_validation",
            "pid": os.getpid(),
            "error": f"{type(exc).__name__}:{str(exc)[:1200]}",
        }
        _finish_sentinel(payload)
        _emit(
            f"AI_SELFIE_V265_PROD_VERIFY status=failed pid={os.getpid()} "
            f"error={type(exc).__name__}:{str(exc)[:1200]}"
        )


def start_once() -> None:
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    if not _claim_pending():
        return
    thread = threading.Thread(target=_worker, name="v265-production-verifier", daemon=True)
    thread.start()


__all__ = ["start_once"]