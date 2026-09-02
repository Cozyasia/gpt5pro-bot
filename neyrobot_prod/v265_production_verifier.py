# -*- coding: utf-8 -*-
"""Temporary one-shot production verifier for stabilized V265.

This module owns no generation algorithm, quality threshold, handler, or fallback. It
claims a persistent sentinel before any network/model/image work, waits for the exact
V265 production owner, then observes the normal standard/strict path. Candidate capture
is read-only: the existing ocular function is delegated unchanged and its returned bytes
and metrics are retained only so a hard quality rejection can still be inspected without
running a third attempt.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import io
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

_SENTINEL = Path("/data/v265_prod_verify_pr110_stability_quality_v1.once")
_ARTIFACT_DIR = Path("/data/v265_prod_verify_pr110_stability_quality_v1")
_FIXTURE_BASE = (
    "https://raw.githubusercontent.com/yakhyo/uniface/"
    "df87c6531f4d1bdad665882d42d658590e724ea4/assets/source"
)
_STARTED = False


def _emit(message: str) -> None:
    print(message, flush=True)


def _write_state(payload: dict[str, Any]) -> None:
    _SENTINEL.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SENTINEL.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with tmp.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(tmp, _SENTINEL)


def _claim_pending() -> bool:
    """Atomically claim this validation before readiness/Gemini/model/image work."""
    _SENTINEL.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(_SENTINEL), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        state = "unknown"
        with contextlib.suppress(Exception):
            state = str(json.loads(_SENTINEL.read_text(encoding="utf-8")).get("status", "unknown"))
        _emit(
            f"AI_SELFIE_V265_VERIFY status=skipped reason=sentinel_exists state={state} sentinel={_SENTINEL}"
        )
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


def _dims(raw: bytes) -> tuple[int, int]:
    from PIL import Image
    with Image.open(io.BytesIO(bytes(raw))) as image:
        return int(image.width), int(image.height)


def _save_artifact(name: str, raw: bytes) -> Path:
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
    w, h = _dims(data)
    _emit(
        f"AI_SELFIE_V265_VERIFY_ARTIFACT name={name} bytes={len(data)} dims={w}x{h} "
        f"sha256={hashlib.sha256(data).hexdigest()[:16]} persisted=true"
    )
    return path


def _production_size(raw: bytes) -> bytes:
    from PIL import Image
    with Image.open(io.BytesIO(bytes(raw))) as opened:
        image = opened.convert("RGB")
        w, h = image.size
        scale = max(1.0, 1856.0 / max(1, min(w, h)), 2304.0 / max(1, max(w, h)))
        if scale > 1.0001:
            image = image.resize(
                (int(round(w * scale)), int(round(h * scale))), Image.Resampling.LANCZOS
            )
        out = io.BytesIO()
        image.save(out, format="PNG", compress_level=2)
        encoded = out.getvalue()
    ow, oh = _dims(encoded)
    _emit(
        f"AI_SELFIE_V265_VERIFY_SIZE input={w}x{h} output={ow}x{oh} scale={scale:.4f} "
        "downscale=false png=true"
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
            pos = obj.tell() if hasattr(obj, "tell") else None
            if hasattr(obj, "seek"):
                obj.seek(0)
            self.raw = bytes(obj.read())
            if pos is not None and hasattr(obj, "seek"):
                obj.seek(pos)
            return True
        raise RuntimeError("could not inspect Telegram InputFile payload")


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
        raise RuntimeError("invalid no-neck probe")
    neck_equal = bool(np.array_equal(target[y0:y1, x0:x1], output[y0:y1, x0:x1]))
    _emit(
        f"AI_SELFIE_V265_VERIFY_PIXELS person_b_pixel_equal={str(person_b_equal).lower()} "
        f"neck_region_equal={str(neck_equal).lower()} firewall_x={firewall_x} "
        f"neck_box={x0},{y0},{x1},{y1}"
    )
    return person_b_equal, neck_equal


def _contact_sheet(source: bytes, stage1: bytes, final: bytes) -> bytes:
    from PIL import Image, ImageDraw

    def panel(raw: bytes, left_only: bool) -> Image.Image:
        with Image.open(io.BytesIO(bytes(raw))) as opened:
            image = opened.convert("RGB")
        if left_only:
            image = image.crop((0, 0, max(1, int(image.width * 0.55)), image.height))
        image.thumbnail((210, 245), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (220, 270), "white")
        canvas.paste(image, ((220 - image.width) // 2, 18))
        return canvas

    sheet = Image.new("RGB", (660, 300), "white")
    for idx, part in enumerate((panel(source, False), panel(stage1, True), panel(final, True))):
        sheet.paste(part, (idx * 220, 24))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 5), "SOURCE A", fill="black")
    draw.text((228, 5), "STAGE-1 A", fill="black")
    draw.text((448, 5), "FINAL V265 A", fill="black")
    out = io.BytesIO()
    sheet.save(out, format="JPEG", quality=62, optimize=True)
    return out.getvalue()


def _emit_thumbnail(raw: bytes) -> None:
    encoded = base64.b64encode(bytes(raw)).decode("ascii")
    chunks = [encoded[i:i + 3500] for i in range(0, len(encoded), 3500)]
    _emit(f"AI_SELFIE_V265_VERIFY_THUMB_BEGIN chunks={len(chunks)} bytes={len(raw)}")
    for i, chunk in enumerate(chunks, 1):
        _emit(f"AI_SELFIE_V265_VERIFY_THUMB chunk={i}/{len(chunks)} data={chunk}")
    _emit("AI_SELFIE_V265_VERIFY_THUMB_END")


def _metric_block(metrics: dict[str, float]) -> dict[str, float]:
    return {
        "identity": float(metrics.get("identity_similarity_cosine", 0.0)),
        "left_eye": float(metrics.get("left_eye_error", 1.0)),
        "right_eye": float(metrics.get("right_eye_error", 1.0)),
        "eye_asymmetry": float(metrics.get("eye_asymmetry_delta", 0.0)),
        "interocular": float(metrics.get("interocular_ratio_delta", 1.0)),
        "nose_mouth": float(metrics.get("nose_mouth_axis_delta", 1.0)),
        "inner_nme": float(metrics.get("inner_face_landmark_nme", 1.0)),
    }


def _log_candidate(path: str, metrics: dict[str, float], hard: bool, failures: list[str]) -> None:
    m = _metric_block(metrics)
    _emit(
        f"AI_SELFIE_V265_VERIFY_METRICS path={path} identity={m['identity']:.6f} "
        f"left_eye={m['left_eye']:.6f} right_eye={m['right_eye']:.6f} "
        f"eye_asymmetry={m['eye_asymmetry']:.6f} interocular={m['interocular']:.6f} "
        f"nose_mouth={m['nose_mouth']:.6f} inner_nme={m['inner_nme']:.6f} "
        f"hard_gate={'PASS' if hard else 'FAIL'} failures={'none' if not failures else '|'.join(failures)}"
    )


def _runtime() -> tuple[str, Any | None]:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return name, mod
    return "", None


def _port_open(runtime: Any | None) -> bool:
    if runtime is None:
        return False
    try:
        port = int(getattr(runtime, "PORT", 10000) or 10000)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            return sock.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


def _readiness() -> tuple[str, Any | None, dict[str, Any]]:
    import neyrobot_prod as package
    from neyrobot_prod import dense68_engine_v265 as engine
    from neyrobot_prod import selfie_v211_delivery as delivery
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer
    from neyrobot_prod import selfie_v265_single_owner as v265
    from neyrobot_prod import v265_strict_runtime_safety as safety

    runtime_name, runtime = _runtime()
    owner = getattr(transfer, "_true_face_transfer", None)
    delivery_owner = getattr(delivery, "_deliver", None)
    checks = {
        "process_started": bool(runtime is not None and callable(getattr(runtime, "main", None)) and _port_open(runtime)),
        "bootstrap_v265": bool(getattr(package, "PRODUCTION_SELFIE_RUNTIME", "") == "v265" and getattr(v265, "_INSTALLED", False)),
        "owner_registered": bool(owner is v265._true_face_transfer_v265),
        "delivery_owner_registered": bool(delivery_owner is v265._deliver_original_only),
        "dense68_available": bool(callable(getattr(engine, "transfer_attempt", None)) and callable(getattr(engine, "apply_ocular_lock", None))),
        "strict_safety": bool(getattr(safety, "_INSTALLED", False)),
        "gemini_configured": bool(os.environ.get("GEMINI_IMAGE_API_KEY", "").strip()),
    }
    checks["safe_to_begin"] = all(checks.values())
    return runtime_name, runtime, checks


async def _verify_async(runtime: Any) -> None:
    from neyrobot_prod import dense68_engine_v265 as engine
    from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
    from neyrobot_prod import selfie_v263_dense_identity_lock as v263
    from neyrobot_prod import selfie_v265_single_owner as v265

    pid_start = os.getpid()
    source = await _download_fixture("verify_now_2024.jpg")
    hero = await _download_fixture("verify_curie.jpg")
    _save_artifact("01_source_person_a.jpg", source)
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

    stage_hash = hashlib.sha256(stage1).digest()
    source_hash = hashlib.sha256(source).digest()
    captured: list[tuple[bytes, dict[str, float]]] = []
    base_ocular = engine.apply_ocular_lock

    def observed_ocular(*args: Any, **kwargs: Any):
        result, metrics = base_ocular(*args, **kwargs)
        try:
            if hashlib.sha256(bytes(args[0])).digest() == stage_hash and hashlib.sha256(bytes(args[2])).digest() == source_hash:
                captured.append((bytes(result), dict(metrics)))
        except Exception:
            pass
        return result, metrics

    engine.apply_ocular_lock = observed_ocular
    owner_error: BaseException | None = None
    final: bytes | None = None
    provider = ""
    try:
        try:
            final, provider = await v265._true_face_transfer_v265(runtime, stage1, source, 3)
        except BaseException as exc:
            owner_error = exc
    finally:
        engine.apply_ocular_lock = base_ocular

    for idx, (candidate, metrics) in enumerate(captured):
        path = "standard" if idx == 0 else "strict"
        _save_artifact(f"04_{path}_v265.png", candidate)
        hard, failures = v265.production_gate(metrics)
        _log_candidate(path, metrics, hard, failures)

    selected = str(getattr(runtime, "AI_SELFIE_LAST_IDENTITY_PATH", "") or "")
    if final is not None:
        diagnostic_final = bytes(final)
        diagnostic_metrics = dict(getattr(runtime, "AI_SELFIE_LAST_IDENTITY_METRICS", {}) or {})
        result_kind = "pass"
    elif captured:
        diagnostic_final, diagnostic_metrics = captured[-1]
        result_kind = "quality_fail"
    else:
        if owner_error is not None and "insufficient container memory headroom" in str(owner_error):
            result_kind = "strict_memory_block"
            _write_state({
                "status": "completed",
                "result": result_kind,
                "pid": os.getpid(),
                "process_restart": False,
                "error": f"{type(owner_error).__name__}:{str(owner_error)}",
            })
            _emit(
                f"AI_SELFIE_V265_PROD_VERIFY status={result_kind} pid_start={pid_start} pid_end={os.getpid()} "
                "process_restart=false strict_heavy_work_started=false"
            )
            return
        raise RuntimeError(f"V265 produced no observable candidate: {owner_error}")

    _save_artifact("06_final_diagnostic_v265.png", diagnostic_final)
    final_dims = _dims(diagnostic_final)
    final_png = diagnostic_final.startswith(b"\x89PNG\r\n\x1a\n")
    hard_ok, hard_failures = v265.production_gate(diagnostic_metrics)
    yunet_path = await v253._ensure_yunet_model()
    dense_path, recognition_path = await v263._ensure_identity_models()
    if not dense_path or not recognition_path:
        raise RuntimeError("PIPNet/MobileFace model resolution missing")
    person_b_equal, neck_equal = _pixel_probes(stage1, diagnostic_final, yunet_path)

    sink = _DocumentSink()
    delivered = await v265._deliver_original_only(
        sink, diagnostic_final, "V265 production verifier", prefer_document=True
    )
    delivery_exact = bool(sink.calls == 1 and sink.raw == diagnostic_final and delivered == diagnostic_final)
    contact = _contact_sheet(source, stage1, diagnostic_final)
    _save_artifact("07_visual_contact_sheet.jpg", contact)
    _emit_thumbnail(contact)

    m = _metric_block(diagnostic_metrics)
    pid_end = os.getpid()
    payload = {
        "status": "completed",
        "result": "pass" if hard_ok and owner_error is None else result_kind,
        "pid_start": pid_start,
        "pid_end": pid_end,
        "process_restart": pid_start != pid_end,
        "stage1_dims": f"{stage1_dims[0]}x{stage1_dims[1]}",
        "final_dims": f"{final_dims[0]}x{final_dims[1]}",
        "model": model,
        "provider": provider,
        "selected": selected,
        "standard_observed": len(captured) >= 1,
        "strict_observed": len(captured) >= 2,
        **m,
        "hard_gate": hard_ok,
        "hard_gate_failures": hard_failures,
        "person_b_untouched": person_b_equal,
        "no_neck": neck_equal,
        "delivery_exact": delivery_exact,
        "final_png": final_png,
        "owner_error": "" if owner_error is None else f"{type(owner_error).__name__}:{str(owner_error)}",
    }
    _write_state(payload)
    _emit(
        f"AI_SELFIE_V265_PROD_VERIFY status={payload['result']} pid_start={pid_start} pid_end={pid_end} "
        f"process_restart={str(pid_start != pid_end).lower()} stage1_dims={payload['stage1_dims']} "
        f"final_dims={payload['final_dims']} standard_observed={str(len(captured) >= 1).lower()} "
        f"strict_observed={str(len(captured) >= 2).lower()} selected={selected or 'none'} "
        f"identity={m['identity']:.6f} left_eye={m['left_eye']:.6f} right_eye={m['right_eye']:.6f} "
        f"eye_asymmetry={m['eye_asymmetry']:.6f} interocular={m['interocular']:.6f} "
        f"nose_mouth={m['nose_mouth']:.6f} inner_nme={m['inner_nme']:.6f} "
        f"hard_gate={'PASS' if hard_ok else 'FAIL'} person_b_untouched={str(person_b_equal).lower()} "
        f"no_neck={str(neck_equal).lower()} delivery_exact={str(delivery_exact).lower()} "
        f"final_png={str(final_png).lower()} legacy_fallback=false"
    )


def _worker() -> None:
    runtime_name = ""
    runtime = None
    readiness: dict[str, Any] = {}
    deadline = time.monotonic() + 180.0
    last_report = 0.0
    while time.monotonic() < deadline:
        try:
            runtime_name, runtime, readiness = _readiness()
            if readiness.get("safe_to_begin"):
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

    if runtime is None or not readiness.get("safe_to_begin"):
        _write_state({"status": "failed", "phase": "runtime_wait", "pid": os.getpid(), "readiness": readiness})
        _emit("AI_SELFIE_V265_VERIFY status=failed phase=runtime_wait " + json.dumps(readiness, sort_keys=True))
        return

    _write_state({
        "status": "started",
        "pid": os.getpid(),
        "time": time.time(),
        "git_commit": os.environ.get("RENDER_GIT_COMMIT", ""),
        "runtime_name": runtime_name,
        "readiness": readiness,
    })
    _emit(
        f"AI_SELFIE_V265_VERIFY status=started pid={os.getpid()} sentinel={_SENTINEL} "
        "heavy_started_after_sentinel=true target_short=1856 target_long=2304"
    )
    try:
        asyncio.run(_verify_async(runtime))
    except BaseException as exc:
        _write_state({
            "status": "failed",
            "phase": "production_validation",
            "pid": os.getpid(),
            "error": f"{type(exc).__name__}:{str(exc)[:1200]}",
        })
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
    threading.Thread(target=_worker, name="v265-production-verifier-pr110", daemon=True).start()


__all__ = ["start_once"]
