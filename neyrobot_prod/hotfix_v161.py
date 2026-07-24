# -*- coding: utf-8 -*-
"""Neyro-Bot v161: high-fidelity Roman identity with proven user preservation.

V160 remains the fallback for every celebrity and for any unavailable provider.
For Roman Abramovich, v161 restores the previously successful architecture:

* build a one-person right-side scene plate;
* lock Roman's face with PiAPI from the owner reference pack (OpenAI fallback);
* preserve and composite the user's original source pixels on the left;
* run strict two-person layout, identity and naturalness checks;
* fall back to the coherent v160 whole-frame renderer only if the hybrid path
  cannot run or does not produce a verified result.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Awaitable, Callable

from PIL import Image, ImageOps

from . import hotfix_v160 as previous

import celebrity_selfie_v139 as v139
import celebrity_selfie_v142 as v142
import celebrity_selfie_v143 as v143
import celebrity_selfie_v144 as v144
import celebrity_selfie_v145 as v145
import celebrity_selfie_v150 as v150
import celebrity_selfie_v156 as renderer
import celebrity_selfie_v158 as release

VERSION = "v161-roman-hybrid-identity-2026-07-24"
_ROMAN_NAME = "роман абрамович"
_LOCK = threading.RLock()
_PIPELINE_GATE = asyncio.Lock()
_WORKER_STARTED = False

_V156_ORIGINAL_RUN = renderer._run_v156_generation
_V158_FIXED_PATHS = release._fixed_reference_paths
_ORIGINAL_FAILURE_MESSAGE = v139._failure_message
_ORIGINAL_V142_PLATES = v142._make_plate_candidates
_ORIGINAL_V143_CELEBRITIES = v143._celebrity_variants

log = logging.getLogger("gpt-bot.hotfix-v161")


def _normalise(value: Any) -> str:
    return str(value or "").strip().casefold().replace("ё", "е")


def _is_roman_name(value: Any) -> bool:
    name = _normalise(value)
    return name == _ROMAN_NAME or ("роман" in name and "абрамович" in name)


def _image_dimensions(raw: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(raw)) as opened:
        image = ImageOps.exif_transpose(opened)
        image.verify()
        return int(image.width), int(image.height)


def _cache_reference(raw: bytes, index: int) -> str:
    cache_root = Path(os.environ.get("CELEBRITY_FIXED_REF_CACHE") or "/tmp/neyrobot_fixed_refs") / release.ROMAN_ID / "v2"
    cache_root.mkdir(parents=True, exist_ok=True)
    target = cache_root / f"{index:02d}.jpg"
    digest = hashlib.sha256(raw).hexdigest()
    digest_path = target.with_suffix(".jpg.sha256")
    valid = (
        target.exists()
        and target.stat().st_size == len(raw)
        and digest_path.exists()
        and digest_path.read_text(encoding="ascii").strip() == digest
    )
    if not valid:
        target.write_bytes(raw)
        digest_path.write_text(digest, encoding="ascii")
    return str(target)


def _decode_full_parts(directory: Path, index: int) -> str | None:
    parts = sorted(directory.glob("part_*.txt"))
    if not parts:
        return None
    encoded = "".join(path.read_text(encoding="ascii") for path in parts)
    raw = release._decode_asset_text(encoded, f"roman-full-{index:02d}")
    width, height = _image_dimensions(raw)
    if min(width, height) < 400 or len(raw) < 20_000:
        raise ValueError(
            f"owner reference {index} is too small for identity locking: {width}x{height}, {len(raw)} bytes"
        )
    return _cache_reference(raw, index)


def _full_reference_paths() -> list[str]:
    fallback = list(_V158_FIXED_PATHS() or [])
    if len(fallback) != 3:
        raise RuntimeError("Roman reference fallback pack must contain exactly three images")
    result: list[str] = []
    for index, fallback_path in enumerate(fallback, start=1):
        full_dir = release._PACK_ROOT / "full" / f"{index:02d}"
        upgraded = _decode_full_parts(full_dir, index)
        result.append(upgraded or fallback_path)
    if len(result) != 3 or len(set(result)) != 3:
        raise RuntimeError("Roman reference pack did not materialise as three unique files")
    return result


def _reference_dimensions() -> list[str]:
    rows: list[str] = []
    for path in _full_reference_paths():
        try:
            width, height = _image_dimensions(Path(path).read_bytes())
            rows.append(f"{width}x{height}")
        except Exception:
            rows.append("invalid")
    return rows


def _patch_reference_pack() -> bool:
    try:
        release._fixed_reference_paths = _full_reference_paths
        # Existing functions in v158 resolve this name through the module global
        # dictionary, so reference routing/ranking immediately receives v2 paths.
        paths = _full_reference_paths()
        return len(paths) == 3
    except Exception as exc:
        log.exception("v161 reference-pack patch failed: %r", exc)
        return False


async def _roman_plate_candidates(
    mod: Any,
    scene: str,
    aspect: str,
    user_photo: bytes,
    debug: dict[str, Any],
) -> list[dict[str, Any]]:
    """Create one close anonymous right-side companion plate.

    Direct scene providers from the proven v144 flow are tried first. Comet is a
    provider-safe fallback using the same one-person/right-side composition.
    """
    rows = await v144._make_plate_candidates(mod, scene, aspect, user_photo, debug)
    if rows:
        debug["v161_plate_route"] = "v144-direct-providers"
        return rows

    safe_aspect = v144._normalise_aspect(aspect)
    lighting = v142._lighting_hint(user_photo)
    candidates: list[dict[str, Any]] = []
    for index in range(2):
        label = f"v161_roman_plate_comet_{index + 1}"
        stage = v139._stage_start(debug, label, "comet", aspect=safe_aspect, people=1)
        try:
            prompt = v144._scene_prompt(
                scene,
                safe_aspect,
                index,
                lighting,
                rescue=bool(index),
            )
            raw = await v150._comet_scene(prompt, safe_aspect, debug)
            problem = v143._plate_problem(raw, label)
            if problem:
                raise v139.PipelineError("structural_qc", problem)
            row = {
                "label": label,
                "provider": "comet:one-person-plate",
                "score": round(v142._plate_score(raw), 2),
                "output": raw,
                "aspect": safe_aspect,
            }
            candidates.append(row)
            debug.setdefault("scene_candidates", []).append(
                {key: value for key, value in row.items() if key != "output"}
            )
            v139._stage_finish(stage, "ok", score=row["score"], bytes=len(raw), people=1)
        except Exception as exc:
            v139._record_error(debug, stage, exc)
    candidates.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    if candidates:
        debug["v161_plate_route"] = "comet-one-person-fallback"
    return candidates


async def _run_roman_hybrid(
    mod: Any,
    user_photo: bytes,
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    previous_result: bytes | None = None,
    *,
    additional_user_refs: list[bytes] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    del previous_result
    # v143/v145 use module-level strategy functions. All Celebrity Selfie calls
    # are serialised by _PIPELINE_GATE while these two dependencies are swapped.
    old_plates = v142._make_plate_candidates
    old_celebrities = v143._celebrity_variants
    os.environ.setdefault("CELEBRITY_V145_CELEBRITY_PROVIDERS", "piapi,openai")
    os.environ.setdefault("CELEBRITY_V145_PIAPI_MODES", "face-swap,multi-face-swap")
    os.environ.setdefault("CELEBRITY_V145_PIAPI_REFERENCE_ATTEMPTS", "3")
    os.environ.setdefault("CELEBRITY_V143_MIN_VISUAL_NATURALNESS", "66")
    try:
        v142._make_plate_candidates = _roman_plate_candidates
        v143._celebrity_variants = v145._celebrity_variants
        output, debug = await v145._run_v145_generation(
            mod,
            user_photo,
            celebrity_refs,
            celebrity_name,
            scene,
            additional_user_refs=additional_user_refs,
        )
        debug = dict(debug or {})
        selected = dict(debug.get("selected") or {})
        selected.update({
            "pipeline": "v161-roman-hybrid",
            "user_pixel_preserved": True,
            "user_face_regenerated": False,
            "celebrity_identity_method": selected.get("celebrity_provider") or "piapi/openai-lock",
        })
        debug.update({
            "version": VERSION,
            "pipeline": "v161-roman-hybrid",
            "architecture": "one-person-scene+piapi-celebrity-lock+original-user-pixel-composite",
            "reference_dimensions": _reference_dimensions(),
            "selected": selected,
            "failure_class": None,
        })
        return output, debug
    finally:
        v142._make_plate_candidates = old_plates
        v143._celebrity_variants = old_celebrities


async def _run_v161_generation(
    mod: Any,
    user_photo: bytes,
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    previous_result: bytes | None = None,
    *,
    additional_user_refs: list[bytes] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    async with _PIPELINE_GATE:
        if not _is_roman_name(celebrity_name):
            return await _V156_ORIGINAL_RUN(
                mod,
                user_photo,
                celebrity_refs,
                celebrity_name,
                scene,
                previous_result=previous_result,
                additional_user_refs=additional_user_refs,
            )

        hybrid_error = ""
        try:
            return await _run_roman_hybrid(
                mod,
                user_photo,
                celebrity_refs,
                celebrity_name,
                scene,
                previous_result=previous_result,
                additional_user_refs=additional_user_refs,
            )
        except Exception as exc:
            hybrid_error = v139._safe_error(exc)
            log.warning("v161 Roman hybrid failed, using v160 fallback: %s", hybrid_error)

        try:
            output, debug = await _V156_ORIGINAL_RUN(
                mod,
                user_photo,
                celebrity_refs,
                celebrity_name,
                scene,
                previous_result=previous_result,
                additional_user_refs=additional_user_refs,
            )
            debug = dict(debug or {})
            debug.update({
                "version": VERSION,
                "pipeline": "v161-v160-fallback",
                "v161_hybrid_error": hybrid_error[:700],
                "reference_dimensions": _reference_dimensions(),
            })
            return output, debug
        except Exception as exc:
            debug = dict(getattr(exc, "debug", None) or {})
            debug.update({
                "version": VERSION,
                "pipeline": "v161-both-routes-rejected",
                "v161_hybrid_error": hybrid_error[:700],
                "reference_dimensions": _reference_dimensions(),
            })
            if isinstance(exc, v139.PipelineError):
                exc.debug = debug
            raise


def _failure_message(exc: BaseException, debug: dict[str, Any]) -> str:
    category = getattr(exc, "category", None) or debug.get("failure_class")
    if str(category) == "identity_pipeline" and str(debug.get("version") or "").startswith("v161"):
        return (
            "Все созданные варианты были отклонены контролем качества: ни один кадр одновременно не сохранил "
            "точное лицо пользователя, лицо выбранной персоны и цельную естественную сцену."
        )
    return _ORIGINAL_FAILURE_MESSAGE(exc, debug)


def _patch_pipeline() -> bool:
    with _LOCK:
        try:
            _patch_reference_pack()
            renderer._run_v156_generation = _run_v161_generation
            v139._run_two_stage_generation = _run_v161_generation
            v139.selfie._run_v156_generation = _run_v161_generation
            v139.selfie._run_v139_generation = _run_v161_generation
            v139._failure_message = _failure_message
            return True
        except Exception as exc:
            log.exception("v161 pipeline patch failed: %r", exc)
            return False


def _patch_version_contract() -> None:
    previous.VERSION = VERSION
    previous._cmd_version = _cmd_version
    with contextlib.suppress(Exception):
        import neyrobot_prod
        from neyrobot_prod import bootstrap, versioning
        neyrobot_prod.VERSION = VERSION
        bootstrap.VERSION = VERSION
        versioning.VERSION = VERSION


async def _cmd_version(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    previous._install_celebrity_release()
    previous._patch_qc()
    _patch_pipeline()
    mod = previous._runtime_module()
    if mod is not None:
        previous._patch_runtime(mod)
        for attr in ("APP_VERSION", "RELEASE_VERSION", "PRODUCTION_HARDENING_VERSION", "PATCH_VERSION"):
            setattr(mod, attr, VERSION)

    refs: list[str] = []
    ref_error = ""
    try:
        refs = _full_reference_paths()
    except Exception as exc:
        ref_error = f"{type(exc).__name__}: {exc}"
    dimensions = _reference_dimensions() if refs else []
    medical_text = bool(mod and getattr(getattr(mod, "_medical_analyze_text", None), "_prod_v120_medical", False))
    medical_image = bool(mod and getattr(getattr(mod, "_medical_analyze_image", None), "_prod_v120_medical", False))
    methods = sorted((getattr(mod, "YOO_DIRECT_METHODS", {}) or {}).keys()) if mod is not None else []
    packs = previous._packages(mod) if mod is not None else previous._DEFAULT_PACKAGES
    lines = [
        f"✅ Код запущен: {VERSION}",
        "entrypoint=main.py",
        "start_command=python -u main.py",
        "release_overlay=v161",
        "celebrity_selfie_menu=v124-priority-catalog-wizard",
        "celebrity_selfie_photo_router=v159-priority-before-generic-photo",
        "celebrity_selfie_render=v161-roman-hybrid+v160-fallback",
        "roman_hybrid_primary=one-person-scene+piapi-celebrity-lock+original-user-pixels",
        "roman_hybrid_qc=strict-two-face-layout+identity+naturalness",
        f"fixed_roman_reference_count={len(refs)}",
        f"fixed_roman_reference_dimensions={','.join(dimensions) or '-'}",
        f"fixed_roman_reference_pack={'ready' if len(refs) == 3 else 'warning'}",
        f"fixed_roman_reference_error={ref_error or '-'}",
        "celebrity_selfie_duplicate_failure=blocked",
        f"credit_catalog={','.join(f'{c}:{r}' for c, r in sorted(packs.items()))}",
        f"credit_yookassa_methods={','.join(methods)}",
        f"medical_text_route={'v120' if medical_text else 'legacy'}",
        f"medical_image_route={'v120' if medical_image else 'legacy'}",
        f"medical_card={getattr(mod, 'MEDICAL_CARD_VERSION', '—') if mod is not None else '—'}",
        f"medical_answer_ui={getattr(mod, 'MEDICAL_ANSWER_UI_VERSION', '—') if mod is not None else '—'}",
    ]
    await update.effective_message.reply_text("\n".join(lines)[:3900])
    raise ApplicationHandlerStop


def _patch_runtime(mod: Any) -> bool:
    try:
        previous._patch_runtime(mod)
        _patch_pipeline()
        for attr in ("APP_VERSION", "RELEASE_VERSION", "PRODUCTION_HARDENING_VERSION", "PATCH_VERSION"):
            setattr(mod, attr, VERSION)
        mod._V161_ROMAN_HYBRID_ACTIVE = True
        return True
    except Exception as exc:
        log.exception("v161 runtime patch failed: %r", exc)
        return False


def _start_worker() -> None:
    global _WORKER_STARTED
    if _WORKER_STARTED:
        return
    _WORKER_STARTED = True

    def worker() -> None:
        stable = 0
        for _ in range(3600):
            _patch_version_contract()
            pipeline_ok = _patch_pipeline()
            mod = previous._runtime_module()
            runtime_ok = bool(mod is not None and _patch_runtime(mod))
            stable = stable + 1 if pipeline_ok and runtime_ok else 0
            if stable >= 120:
                return
            time.sleep(0.1)

    threading.Thread(target=worker, name="neyrobot-hotfix-v161", daemon=True).start()


def install_early() -> None:
    previous.install_early()
    _patch_reference_pack()
    _patch_pipeline()
    _patch_version_contract()
    _start_worker()


__all__ = [
    "VERSION",
    "install_early",
    "_full_reference_paths",
    "_reference_dimensions",
    "_roman_plate_candidates",
    "_run_roman_hybrid",
    "_run_v161_generation",
    "_patch_pipeline",
    "_patch_runtime",
    "_cmd_version",
]
