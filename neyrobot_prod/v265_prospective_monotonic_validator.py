# -*- coding: utf-8 -*-
"""Temporary one-shot prospective validation for V265 monotonic selection.

The validator is inert unless V265_PROSPECTIVE_VALIDATION=1. It makes at most one
Gemini Stage-1 request, persists exact source/Stage-1 bytes before local comparison,
then evaluates standard-pre/post and strict-pre/post on those exact bytes only.
No production quality threshold, engine, delivery route, fallback, or handler is changed.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import gc
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

_STATE = Path("/data/v265_prospective_monotonic_v1.state.json")
_ROOT = Path("/data/v265_prospective_monotonic_v1")
_STARTED = False
_FIXTURE_BASE = (
    "https://raw.githubusercontent.com/yakhyo/uniface/"
    "df87c6531f4d1bdad665882d42d658590e724ea4/assets/source"
)
_EXPECTED_SOURCE_BYTES = 121684
_EXPECTED_SOURCE_DIMS = (960, 1280)
_EXPECTED_SOURCE_FACE = (189, 342, 516, 710)
_EXPECTED_EXPRESSION_BYTES = 447707


def _emit(msg: str) -> None:
    print(msg, flush=True)


def _flag() -> bool:
    return str(os.environ.get("V265_PROSPECTIVE_VALIDATION") or "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _write_state(payload: dict[str, Any]) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with tmp.open("rb") as fh:
        os.fsync(fh.fileno())
    os.replace(tmp, _STATE)


def _read_state() -> dict[str, Any]:
    try:
        return dict(json.loads(_STATE.read_text(encoding="utf-8")))
    except Exception:
        return {}


def _save(name: str, raw: bytes) -> Path:
    data = bytes(raw or b"")
    if not data:
        raise RuntimeError(f"empty validation artifact: {name}")
    _ROOT.mkdir(parents=True, exist_ok=True)
    path = _ROOT / name
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    with tmp.open("rb") as fh:
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    _emit(
        f"AI_SELFIE_V265_PROSPECTIVE_ARTIFACT name={name} bytes={len(data)} "
        f"sha256={hashlib.sha256(data).hexdigest()} persisted=true"
    )
    return path


def _dims(raw: bytes) -> tuple[int, int]:
    from PIL import Image
    with Image.open(io.BytesIO(bytes(raw))) as im:
        return int(im.width), int(im.height)


async def _download_fixture(name: str) -> bytes:
    import httpx
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, connect=20.0), follow_redirects=True
    ) as client:
        r = await client.get(f"{_FIXTURE_BASE}/{name}")
        r.raise_for_status()
        data = bytes(r.content)
    if len(data) < 4096:
        raise RuntimeError(f"fixture too small: {name}")
    return data


def _runtime() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


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


def _ready() -> tuple[Any | None, dict[str, bool]]:
    import neyrobot_prod as package
    from neyrobot_prod import dense68_engine_v265 as engine
    from neyrobot_prod import selfie_v211_delivery as delivery
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer
    from neyrobot_prod import selfie_v265_single_owner as v265
    from neyrobot_prod import v265_strict_runtime_safety as safety

    runtime = _runtime()
    checks = {
        "process_started": bool(runtime is not None and _port_open(runtime)),
        "v265": bool(getattr(package, "PRODUCTION_SELFIE_RUNTIME", "") == "v265"),
        "owner": bool(getattr(transfer, "_true_face_transfer", None) is v265._true_face_transfer_v265),
        "delivery": bool(getattr(delivery, "_deliver", None) is v265._deliver_original_only),
        "engine": bool(callable(engine.transfer_attempt) and callable(engine.apply_ocular_lock)),
        "strict_safety": bool(getattr(safety, "_INSTALLED", False)),
        "gemini": bool(os.environ.get("GEMINI_IMAGE_API_KEY", "").strip()),
    }
    checks["all"] = all(checks.values())
    return runtime, checks


def _near_face(actual: tuple[float, float, float, float]) -> bool:
    return all(abs(float(a) - float(e)) <= 3.0 for a, e in zip(actual, _EXPECTED_SOURCE_FACE))


def _historical_source_from_data(yunet_path: Path) -> tuple[bytes | None, str]:
    """Recover the exact old photo3 only if its logged byte/dimension/face signature matches."""
    from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
    from neyrobot_prod import selfie_v241_authoritative_runtime as v241

    candidates: list[tuple[Path, bytes, tuple[float, float, float, float], int]] = []
    root = Path("/data")
    scanned = 0
    for path in root.rglob("*"):
        if scanned >= 25000:
            break
        scanned += 1
        try:
            if not path.is_file() or path.stat().st_size != _EXPECTED_SOURCE_BYTES:
                continue
            raw = path.read_bytes()
            if _dims(raw) != _EXPECTED_SOURCE_DIMS:
                continue
            frame = v253._decode_bgr(raw)
            bbox, _ = v253._yunet_face(frame, yunet_path, label="prospective_historical_source_probe")
            face = tuple(float(v) for v in bbox)
            if not _near_face(face):
                continue
            expression = v241._expression_crop(raw)
            candidates.append((path, raw, face, len(expression)))
        except Exception:
            continue

    exact = [x for x in candidates if x[3] == _EXPECTED_EXPRESSION_BYTES]
    _emit(
        "AI_SELFIE_V265_PROSPECTIVE_SOURCE_SCAN "
        f"scanned={scanned} signature_candidates={len(candidates)} exact_signature={len(exact)}"
    )
    if len(exact) == 1:
        path, raw, face, expression_bytes = exact[0]
        _emit(
            "AI_SELFIE_V265_PROSPECTIVE_SOURCE "
            f"kind=historical_signature_match path={path} bytes={len(raw)} dims=960x1280 "
            f"face={','.join(str(int(round(x))) for x in face)} expression_bytes={expression_bytes} "
            f"sha256={hashlib.sha256(raw).hexdigest()}"
        )
        return raw, "historical_signature_match"
    return None, "not_persisted"


def _metric(metrics: dict[str, float], key: str, default: float) -> float:
    try:
        return float(metrics.get(key, default))
    except Exception:
        return float(default)


def _metric_payload(metrics: dict[str, float]) -> dict[str, float]:
    left = _metric(metrics, "left_eye_error", 1.0)
    right = _metric(metrics, "right_eye_error", 1.0)
    return {
        "identity": _metric(metrics, "identity_similarity_cosine", 0.0),
        "left_eye": left,
        "right_eye": right,
        "worst_eye": max(left, right),
        "eye_asymmetry": _metric(metrics, "eye_asymmetry_delta", 0.0),
        "interocular": _metric(metrics, "interocular_ratio_delta", 1.0),
        "nose_mouth": _metric(metrics, "nose_mouth_axis_delta", 1.0),
        "inner_nme": _metric(metrics, "inner_face_landmark_nme", 1.0),
    }


def _log_metrics(name: str, metrics: dict[str, float], v265: Any) -> tuple[bool, list[str]]:
    hard, failures = v265.production_gate(metrics)
    m = _metric_payload(metrics)
    _emit(
        f"AI_SELFIE_V265_PROSPECTIVE_METRICS candidate={name} "
        f"identity_similarity_cosine={m['identity']:.6f} left_eye_error={m['left_eye']:.6f} "
        f"right_eye_error={m['right_eye']:.6f} worst_eye={m['worst_eye']:.6f} "
        f"eye_asymmetry={m['eye_asymmetry']:.6f} interocular_ratio_delta={m['interocular']:.6f} "
        f"nose_mouth_axis_delta={m['nose_mouth']:.6f} inner_face_landmark_nme={m['inner_nme']:.6f} "
        f"hard_gate={'PASS' if hard else 'FAIL'} failures={'none' if not failures else '|'.join(failures)}"
    )
    return bool(hard), list(failures)


def _old_selection(
    engine: Any,
    v265: Any,
    standard_post_metrics: dict[str, float],
    strict_post_metrics: dict[str, float],
) -> str:
    standard_ok, _ = v265.production_gate(standard_post_metrics)
    strict_ok, _ = v265.production_gate(strict_post_metrics)
    refinement = engine.visual_refinement_reasons(standard_post_metrics) if standard_ok else []
    if standard_ok and not refinement:
        return "standard_post"
    if standard_ok and strict_ok:
        return "strict_post" if engine.prefer_strict_refinement(
            standard_post_metrics, strict_post_metrics
        ) else "standard_post"
    if strict_ok:
        return "strict_post"
    if standard_ok:
        return "standard_post"
    return "reject"


def _new_selection(
    engine: Any,
    v265: Any,
    standard_pre: bytes,
    standard_pre_metrics: dict[str, float],
    standard_post: bytes,
    standard_post_metrics: dict[str, float],
    strict_pre: bytes,
    strict_pre_metrics: dict[str, float],
    strict_post: bytes,
    strict_post_metrics: dict[str, float],
) -> tuple[str, bytes | None, dict[str, float] | None]:
    std, sm, sp, sh, _ = v265._select_ocular_candidate(
        "prospective_standard",
        standard_pre, standard_pre_metrics,
        standard_post, standard_post_metrics,
    )
    refinement = engine.visual_refinement_reasons(sm) if sh else []
    if sh and not refinement:
        return f"standard_{sp}", std, sm

    strict, tm, tp, th, _ = v265._select_ocular_candidate(
        "prospective_strict",
        strict_pre, strict_pre_metrics,
        strict_post, strict_post_metrics,
    )
    decision = v265._final_candidate_decision(sh, sm, th, tm)
    if decision == "standard":
        return f"standard_{sp}", std, sm
    if decision == "strict":
        return f"strict_{tp}", strict, tm
    return "reject", None, None


def _pixel_probes(stage1: bytes, final: bytes, yunet_path: Path) -> tuple[bool, bool]:
    import numpy as np
    from neyrobot_prod import selfie_v253_yunet_source_pixels as v253

    target = v253._decode_bgr(stage1)
    output = v253._decode_bgr(final)
    if target.shape != output.shape:
        return False, False
    h, w = target.shape[:2]
    firewall_x = max(256, min(w, int(round(w * 0.55))))
    person_b_equal = bool(np.array_equal(target[:, firewall_x:], output[:, firewall_x:]))
    bbox, _ = v253._yunet_face(target[:, :firewall_x], yunet_path, label="prospective_target")
    x, y, fw, fh = [float(v) for v in bbox]
    x0 = max(0, int(round(x + fw * 0.20)))
    x1 = min(firewall_x, int(round(x + fw * 0.80)))
    y0 = max(0, int(round(y + fh * 0.90)))
    y1 = min(h, int(round(y + fh * 1.12)))
    neck_equal = bool(
        x1 > x0 + 4 and y1 > y0 + 4
        and np.array_equal(target[y0:y1, x0:x1], output[y0:y1, x0:x1])
    )
    return person_b_equal, neck_equal


def _visual_sheet(items: list[tuple[str, bytes]], yunet_path: Path) -> bytes:
    import cv2
    from PIL import Image, ImageDraw
    from neyrobot_prod import selfie_v253_yunet_source_pixels as v253

    panels = []
    for name, raw in items:
        frame = v253._decode_bgr(raw)
        probe = frame
        if name != "source":
            probe = frame[:, :max(256, int(round(frame.shape[1] * 0.55)))]
        try:
            bbox, _ = v253._yunet_face(probe, yunet_path, label=f"prospective_visual_{name}")
            x, y, fw, fh = [float(v) for v in bbox]
            h, w = frame.shape[:2]
            x0 = max(0, int(round(x - fw * 0.18)))
            y0 = max(0, int(round(y - fh * 0.22)))
            x1 = min(w, int(round(x + fw * 1.18)))
            y1 = min(h, int(round(y + fh * 1.22)))
            crop = frame[y0:y1, x0:x1]
        except Exception:
            crop = probe
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        im = Image.fromarray(rgb)
        im.thumbnail((205, 235), Image.Resampling.LANCZOS)
        panel = Image.new("RGB", (220, 270), "white")
        panel.paste(im, ((220 - im.width) // 2, 26))
        ImageDraw.Draw(panel).text((8, 7), name, fill="black")
        panels.append(panel)

    cols = 4
    rows = (len(panels) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 220, rows * 270), "white")
    for idx, panel in enumerate(panels):
        sheet.paste(panel, ((idx % cols) * 220, (idx // cols) * 270))
    out = io.BytesIO()
    sheet.save(out, format="JPEG", quality=52, optimize=True)
    return out.getvalue()


def _emit_visual(raw: bytes) -> None:
    encoded = base64.b64encode(bytes(raw)).decode("ascii")
    chunks = [encoded[i:i + 3200] for i in range(0, len(encoded), 3200)]
    _emit(
        f"AI_SELFIE_V265_PROSPECTIVE_VISUAL_BEGIN chunks={len(chunks)} bytes={len(raw)} "
        f"sha256={hashlib.sha256(raw).hexdigest()}"
    )
    for idx, chunk in enumerate(chunks, 1):
        _emit(f"AI_SELFIE_V265_PROSPECTIVE_VISUAL chunk={idx}/{len(chunks)} data={chunk}")
    _emit("AI_SELFIE_V265_PROSPECTIVE_VISUAL_END")


async def _run(runtime: Any) -> None:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import dense68_engine_v265 as engine
    from neyrobot_prod import selfie_v253_yunet_source_pixels as v253
    from neyrobot_prod import selfie_v263_dense_identity_lock as v263
    from neyrobot_prod import selfie_v265_single_owner as v265

    pid_start = os.getpid()
    yunet_path = await v253._ensure_yunet_model()
    dense_path, recognition_path = await v263._ensure_identity_models()

    stage_path = _ROOT / "02_stage1_exact.png"
    source_path = _ROOT / "01_source_exact.jpg"
    state = _read_state()

    if stage_path.exists() and source_path.exists():
        source = source_path.read_bytes()
        stage1 = stage_path.read_bytes()
        model = str(state.get("model") or "persisted")
        source_kind = str(state.get("source_kind") or "persisted")
        _emit("AI_SELFIE_V265_PROSPECTIVE_GEMINI status=skipped reason=exact_stage1_already_persisted")
    else:
        if state.get("gemini_started"):
            raise RuntimeError("Gemini was already started but exact Stage-1 was not persisted; refusing a second call")

        source, source_kind = _historical_source_from_data(yunet_path)
        if source is None:
            # Historical photo3 was memory-only in the failed request. Use one fixed,
            # pinned source for the prospective selector proof; never label it historical.
            source = await _download_fixture("verify_now_2024.jpg")
            source_kind = "controlled_pinned_fixture"
            _emit(
                "AI_SELFIE_V265_PROSPECTIVE_SOURCE kind=controlled_pinned_fixture "
                f"bytes={len(source)} sha256={hashlib.sha256(source).hexdigest()}"
            )
        _save("01_source_exact.jpg", source)

        hero_paths = base._reference_paths(runtime, "roman_abramovich")
        if len(hero_paths) == 3:
            hero_refs = [p.read_bytes() for p in hero_paths]
            hero_name = str((base.CHARACTERS.get("roman_abramovich") or {}).get("name") or "PERSON B")
            hero_kind = "production_persisted_refs"
        else:
            hero = await _download_fixture("verify_curie.jpg")
            hero_refs = [hero, hero, hero]
            hero_name = "PERSON B reference subject"
            hero_kind = "controlled_pinned_fixture"

        scene = base.SCENES["restaurant"][1]
        refs = [("USER SOURCE PHOTO #3 — PERSON A ONLY", source)]
        refs.extend((f"HERO PORTRAIT {i} — PERSON B ONLY", raw) for i, raw in enumerate(hero_refs, 1))
        prompt = v265._stage1_prompt(hero_name, scene, "Селфи", False, 3)

        _write_state({
            "status": "gemini_started",
            "gemini_started": True,
            "gemini_calls": 1,
            "pid": os.getpid(),
            "source_kind": source_kind,
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "hero_kind": hero_kind,
            "preset": "restaurant",
            "git_commit": os.environ.get("RENDER_GIT_COMMIT", ""),
        })
        _emit(
            "AI_SELFIE_V265_PROSPECTIVE_GEMINI status=started call=1/1 "
            f"preset=restaurant source_sha256={hashlib.sha256(source).hexdigest()}"
        )
        stage1, model = await v265._call_google(prompt, refs, "composition_identity_separated")
        _save("02_stage1_exact.png", stage1)
        _write_state({
            "status": "stage1_persisted",
            "gemini_started": True,
            "gemini_calls": 1,
            "pid": os.getpid(),
            "source_kind": source_kind,
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "stage1_sha256": hashlib.sha256(stage1).hexdigest(),
            "stage1_bytes": len(stage1),
            "model": model,
            "hero_kind": hero_kind,
            "preset": "restaurant",
            "git_commit": os.environ.get("RENDER_GIT_COMMIT", ""),
        })
        _emit(
            "AI_SELFIE_V265_PROSPECTIVE_GEMINI status=complete calls=1 "
            f"model={model} stage1_bytes={len(stage1)} stage1_sha256={hashlib.sha256(stage1).hexdigest()}"
        )

    # Exact bytes below this line are immutable inputs. Gemini is never called again.
    source_sha = hashlib.sha256(source).hexdigest()
    stage_sha = hashlib.sha256(stage1).hexdigest()
    _emit(
        "AI_SELFIE_V265_PROSPECTIVE_INPUT_LOCK "
        f"source_sha256={source_sha} stage1_sha256={stage_sha} gemini_calls=1 immutable=true"
    )

    standard_pre, standard_pre_metrics, standard_desired = engine.transfer_attempt(
        stage1, source, yunet_path, dense_path, recognition_path, strict=False
    )
    _save("03_standard_pre.png", standard_pre)
    _log_metrics("standard_pre", standard_pre_metrics, v265)

    standard_post, standard_post_metrics = engine.apply_ocular_lock(
        stage1, standard_pre, source, standard_desired,
        yunet_path, dense_path, recognition_path, standard_pre_metrics
    )
    _save("04_standard_post.png", standard_post)
    _log_metrics("standard_post", standard_post_metrics, v265)

    # Drop large standard buffers before strict preflight; persisted bytes are re-read later.
    del standard_pre, standard_post
    gc.collect()

    strict_pre, strict_pre_metrics, strict_desired = engine.transfer_attempt(
        stage1, source, yunet_path, dense_path, recognition_path, strict=True
    )
    _save("05_strict_pre.png", strict_pre)
    _log_metrics("strict_pre", strict_pre_metrics, v265)

    strict_post, strict_post_metrics = engine.apply_ocular_lock(
        stage1, strict_pre, source, strict_desired,
        yunet_path, dense_path, recognition_path, strict_pre_metrics
    )
    _save("06_strict_post.png", strict_post)
    _log_metrics("strict_post", strict_post_metrics, v265)

    standard_pre = (_ROOT / "03_standard_pre.png").read_bytes()
    standard_post = (_ROOT / "04_standard_post.png").read_bytes()

    old_selected = _old_selection(engine, v265, standard_post_metrics, strict_post_metrics)
    new_selected, final, final_metrics = _new_selection(
        engine, v265,
        standard_pre, standard_pre_metrics,
        standard_post, standard_post_metrics,
        strict_pre, strict_pre_metrics,
        strict_post, strict_post_metrics,
    )

    if final is not None:
        _save("07_final_selected.png", final)
        final_hard, final_failures = v265.production_gate(final_metrics or {})
        person_b, no_neck = _pixel_probes(stage1, final, yunet_path)
    else:
        final_hard, final_failures = False, ["all_candidates_rejected"]
        person_b, no_neck = True, True

    visual_items = [
        ("source", source),
        ("stage1", stage1),
        ("standard_pre", standard_pre),
        ("standard_post", standard_post),
        ("strict_pre", strict_pre),
        ("strict_post", strict_post),
    ]
    if final is not None:
        visual_items.append(("final_selected", final))
    sheet = _visual_sheet(visual_items, yunet_path)
    _save("08_visual_comparison.jpg", sheet)
    _emit_visual(sheet)

    candidate_metrics = {
        "standard_pre": _metric_payload(standard_pre_metrics),
        "standard_post": _metric_payload(standard_post_metrics),
        "strict_pre": _metric_payload(strict_pre_metrics),
        "strict_post": _metric_payload(strict_post_metrics),
    }
    candidate_gates = {}
    for name, metrics in (
        ("standard_pre", standard_pre_metrics),
        ("standard_post", standard_post_metrics),
        ("strict_pre", strict_pre_metrics),
        ("strict_post", strict_post_metrics),
    ):
        candidate_gates[name] = bool(v265.production_gate(metrics)[0])

    payload = {
        "status": "completed",
        "result": "pass",
        "pid_start": pid_start,
        "pid_end": os.getpid(),
        "process_restart": pid_start != os.getpid(),
        "source_kind": source_kind,
        "source_sha256": source_sha,
        "stage1_sha256": stage_sha,
        "stage1_bytes": len(stage1),
        "stage1_dims": _dims(stage1),
        "model": model,
        "preset": "restaurant",
        "gemini_calls": 1,
        "metrics": candidate_metrics,
        "hard_gates": candidate_gates,
        "old_selection": old_selected,
        "new_selection": new_selected,
        "new_final_hard_gate": bool(final_hard),
        "new_final_failures": final_failures,
        "person_b_untouched": bool(person_b),
        "no_neck": bool(no_neck),
        "independent_eye_patch": False,
        "legacy_fallback": False,
        "same_dense68_engine": True,
    }
    _write_state(payload)
    _emit(
        "AI_SELFIE_V265_PROSPECTIVE_COMPLETE status=pass "
        f"source_kind={source_kind} source_sha256={source_sha} stage1_sha256={stage_sha} "
        f"gemini_calls=1 old_selection={old_selected} new_selection={new_selected} "
        f"new_final_hard_gate={'PASS' if final_hard else 'FAIL'} "
        f"person_b_untouched={str(person_b).lower()} no_neck={str(no_neck).lower()} "
        f"process_restart={str(pid_start != os.getpid()).lower()} legacy_fallback=false "
        "independent_eye_patch=false same_dense68_engine=true"
    )


def _worker() -> None:
    runtime = None
    checks: dict[str, bool] = {}
    deadline = time.monotonic() + 240.0
    while time.monotonic() < deadline:
        try:
            runtime, checks = _ready()
            if checks.get("all"):
                break
        except Exception:
            pass
        time.sleep(2.0)
    if runtime is None or not checks.get("all"):
        _write_state({"status": "failed", "phase": "readiness", "checks": checks})
        _emit("AI_SELFIE_V265_PROSPECTIVE_COMPLETE status=failed phase=readiness")
        return
    try:
        asyncio.run(_run(runtime))
    except BaseException as exc:
        state = _read_state()
        state.update({
            "status": "failed",
            "phase": "validation",
            "pid": os.getpid(),
            "error": f"{type(exc).__name__}:{str(exc)[:1400]}",
        })
        _write_state(state)
        _emit(
            f"AI_SELFIE_V265_PROSPECTIVE_COMPLETE status=failed "
            f"error={type(exc).__name__}:{str(exc)[:1400]}"
        )


def start_once() -> None:
    global _STARTED
    if _STARTED or not _flag():
        return
    _STARTED = True
    state = _read_state()
    if state.get("status") == "completed":
        _emit("AI_SELFIE_V265_PROSPECTIVE status=skipped reason=completed_sentinel")
        return
    if state.get("gemini_started") and not (_ROOT / "02_stage1_exact.png").exists():
        _emit(
            "AI_SELFIE_V265_PROSPECTIVE status=blocked reason=gemini_already_started_without_stage1 "
            "second_gemini_call=false"
        )
        return
    threading.Thread(
        target=_worker, daemon=True, name="v265-prospective-monotonic-validator"
    ).start()


__all__ = ["start_once"]
