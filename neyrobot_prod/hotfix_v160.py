# -*- coding: utf-8 -*-
"""Neyro-Bot v160 Celebrity Selfie delivery rescue.

The v159 routing, payments and medical fixes remain intact. This release tunes
Celebrity Selfie for production delivery without allowing wax figures, collages,
wrong-side identities or broken scenes through the quality gate:

* four independent candidates are attempted instead of three;
* the strict identity/quality gates are returned to a practical high-quality
  range after v157/v158 made them too brittle;
* a coherent near-threshold candidate may pass only when every hard structural
  check is positive and both identities remain strong;
* the generic billing error is suppressed after the selfie pipeline has already
  sent its detailed failure card.
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from typing import Any

VERSION = "v160-selfie-delivery-rescue-2026-07-24"

# These values must be applied before v159 installs v158/v157/v156.
os.environ["CELEBRITY_V156_CANDIDATES"] = "4"
os.environ["CELEBRITY_V156_MIN_USER_SIMILARITY"] = "64"
os.environ["CELEBRITY_V157_MIN_USER_SIMILARITY"] = "64"
os.environ["CELEBRITY_V156_MIN_CELEBRITY_SIMILARITY"] = "70"
os.environ["CELEBRITY_V157_MIN_CELEBRITY_SIMILARITY"] = "70"
os.environ["CELEBRITY_V158_MIN_CELEBRITY_SIMILARITY"] = "70"
os.environ["CELEBRITY_V156_MIN_QUALITY"] = "62"
os.environ["CELEBRITY_V156_EARLY_ACCEPT_TOTAL"] = "80"
os.environ["CELEBRITY_V156_TARGETED_REPAIR"] = "1"

from . import hotfix_v159 as previous

log = logging.getLogger("gpt-bot.hotfix-v160")
_LOCK = threading.RLock()
_QC_ORIGINAL: Any | None = None
_WORKER_STARTED = False

_HARD_CHECKS = (
    "exactly_two_main_adults",
    "user_on_left",
    "celebrity_on_right",
    "separate_identities",
    "real_living_people_not_wax",
    "no_plaque_poster_or_museum_display",
    "one_seamless_scene",
    "scene_match",
)
_HARD_REASON_BLOCKS = (
    "resolution too small",
    "exposure unusable",
    "contrast unusable",
    "expected two main faces",
    "invalid image",
    "wax",
    "statue",
    "mannequin",
    "plaque",
    "poster",
    "museum",
    "collage",
    "split screen",
    "split-screen",
    "extra prominent",
    "wrong side",
    "side swap",
    "blended identit",
    "severe face deformation",
)


def _runtime_module() -> Any | None:
    return previous._runtime_module()


def _hard_structure_ok(result: dict[str, Any]) -> bool:
    if bool(result.get("unknown")):
        return False
    checks = result.get("checks") or {}
    if not isinstance(checks, dict):
        return False
    if any(checks.get(key) is not True for key in _HARD_CHECKS):
        return False
    reason = str(result.get("reason") or "").casefold()
    return not any(token in reason for token in _HARD_REASON_BLOCKS)


async def _candidate_qc_v160(
    mod: Any,
    raw: bytes,
    user_ref: bytes,
    celebrity_ref: bytes,
    scene: str,
    debug: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    original = _QC_ORIGINAL
    if not callable(original):
        raise RuntimeError("v160 QC original is unavailable")
    result = await original(mod, raw, user_ref, celebrity_ref, scene, debug, label)
    if not isinstance(result, dict) or result.get("accepted"):
        return result

    # A narrow rescue band absorbs normal vision-QC variance. It never bypasses
    # the anti-wax/collage/two-person/scene checks and still requires both faces.
    user_score = float(result.get("user_similarity") or 0)
    celebrity_score = float(result.get("celebrity_similarity") or 0)
    face_quality = float(result.get("face_quality") or 0)
    overall_quality = float(result.get("quality") or 0)
    total = float(result.get("total") or 0)
    coherent_near_threshold = bool(
        _hard_structure_ok(result)
        and user_score >= 60
        and celebrity_score >= 68
        and face_quality >= 60
        and overall_quality >= 60
        and total >= 68
    )
    if coherent_near_threshold:
        result["accepted"] = True
        result["accepted_by"] = "v160-coherent-near-threshold"
        result["quality_gate_mode"] = "strict-structure+narrow-identity-band"
        result["reason"] = (
            "v160 accepted a coherent near-threshold candidate after all hard "
            "two-person, identity-separation, anti-wax, anti-collage and scene checks passed; "
            + str(result.get("reason") or "")
        )[:420]
    return result


def _patch_qc() -> bool:
    global _QC_ORIGINAL
    with _LOCK:
        try:
            import celebrity_selfie_v156 as renderer
            current = getattr(renderer, "_candidate_qc", None)
            if getattr(current, "_v160_selfie_qc", False):
                return True
            if not callable(current):
                return False
            _QC_ORIGINAL = current
            _candidate_qc_v160._v160_selfie_qc = True  # type: ignore[attr-defined]
            _candidate_qc_v160._v160_original = current  # type: ignore[attr-defined]
            renderer._candidate_qc = _candidate_qc_v160
            return True
        except Exception as exc:
            log.exception("v160 selfie QC patch failed: %r", exc)
            return False


def _patch_payment_failure_dedupe(mod: Any) -> bool:
    current = getattr(mod, "_try_pay_then_do", None)
    if not callable(current):
        return False
    if getattr(current, "_v160_selfie_failure_dedupe", False):
        return True

    async def pay_then_do(*args: Any, **kwargs: Any):
        remember_kind = str(kwargs.get("remember_kind") or "").casefold()
        if "celebrity_selfie" in remember_kind:
            # The selfie worker sends a detailed retry card itself. Prevent the
            # wallet wrapper from appending a second generic failure message.
            kwargs["silent_failure"] = True
        return await current(*args, **kwargs)

    pay_then_do._v160_selfie_failure_dedupe = True  # type: ignore[attr-defined]
    pay_then_do._v160_original = current  # type: ignore[attr-defined]
    mod._try_pay_then_do = pay_then_do
    return True


def _patch_runtime(mod: Any) -> bool:
    try:
        previous._patch_runtime(mod)
        _patch_payment_failure_dedupe(mod)
        mod.APP_VERSION = VERSION
        mod.RELEASE_VERSION = VERSION
        mod.PRODUCTION_HARDENING_VERSION = VERSION
        mod.PATCH_VERSION = VERSION
        mod._V160_SELFIE_RESCUE_ACTIVE = True
        return True
    except Exception as exc:
        log.exception("v160 runtime patch failed: %r", exc)
        return False


async def _cmd_version(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    release_ok = previous._install_celebrity_release()
    _patch_qc()
    mod = _runtime_module()
    if mod is not None:
        _patch_runtime(mod)

    refs = 0
    ref_error = ""
    with contextlib.suppress(Exception):
        import celebrity_selfie_v158 as release
        refs = len(release._fixed_reference_paths())
    if not refs and previous._RELEASE_ERROR:
        ref_error = previous._RELEASE_ERROR

    medical_text = bool(mod and getattr(getattr(mod, "_medical_analyze_text", None), "_prod_v120_medical", False))
    medical_image = bool(mod and getattr(getattr(mod, "_medical_analyze_image", None), "_prod_v120_medical", False))
    methods = sorted((getattr(mod, "YOO_DIRECT_METHODS", {}) or {}).keys()) if mod is not None else []
    packs = previous._packages(mod) if mod is not None else previous._DEFAULT_PACKAGES
    lines = [
        f"✅ Код запущен: {VERSION}",
        "entrypoint=main.py",
        "start_command=python -u main.py",
        f"release_overlay={'v160' if release_ok else 'v160-selfie-safe-mode'}",
        "celebrity_selfie_menu=v124-priority-catalog-wizard",
        "celebrity_selfie_photo_router=v159-priority-before-generic-photo",
        "celebrity_selfie_render=v160-four-candidate-coherent-rescue",
        "celebrity_selfie_duplicate_failure=blocked",
        "celebrity_selfie_hard_structure_gate=required",
        f"celebrity_selfie_candidates={os.environ.get('CELEBRITY_V156_CANDIDATES', '4')}",
        f"celebrity_selfie_user_gate={os.environ.get('CELEBRITY_V157_MIN_USER_SIMILARITY', '64')}",
        f"celebrity_selfie_celebrity_gate={os.environ.get('CELEBRITY_V158_MIN_CELEBRITY_SIMILARITY', '70')}",
        f"celebrity_selfie_quality_gate={os.environ.get('CELEBRITY_V156_MIN_QUALITY', '62')}",
        f"fixed_roman_reference_count={refs}",
        f"fixed_roman_reference_pack={'ready' if refs == 3 else 'warning'}",
        f"fixed_roman_reference_error={ref_error or '-'}",
        "credit_catalog=" + ",".join(f"{c}:{r}" for c, r in sorted(packs.items())),
        "credit_yookassa_methods=" + ",".join(methods),
        f"medical_text_route={'v120' if medical_text else 'legacy'}",
        f"medical_image_route={'v120' if medical_image else 'legacy'}",
        f"medical_card={getattr(mod, 'MEDICAL_CARD_VERSION', '—') if mod is not None else '—'}",
        f"medical_answer_ui={getattr(mod, 'MEDICAL_ANSWER_UI_VERSION', '—') if mod is not None else '—'}",
    ]
    await update.effective_message.reply_text("\n".join(lines)[:3900])
    raise ApplicationHandlerStop


def _patch_version_contract() -> None:
    previous.VERSION = VERSION
    previous._cmd_version = _cmd_version
    with contextlib.suppress(Exception):
        import neyrobot_prod
        from neyrobot_prod import bootstrap, versioning
        neyrobot_prod.VERSION = VERSION
        bootstrap.VERSION = VERSION
        versioning.VERSION = VERSION
    with contextlib.suppress(Exception):
        previous._install_celebrity_release()


def _start_worker() -> None:
    global _WORKER_STARTED
    if _WORKER_STARTED:
        return
    _WORKER_STARTED = True

    def worker() -> None:
        stable = 0
        for _ in range(3600):
            _patch_version_contract()
            qc_ok = _patch_qc()
            mod = _runtime_module()
            runtime_ok = bool(mod is not None and _patch_runtime(mod))
            stable = stable + 1 if qc_ok and runtime_ok else 0
            if stable >= 120:
                return
            time.sleep(0.1)

    threading.Thread(target=worker, name="neyrobot-hotfix-v160", daemon=True).start()


def install_early() -> None:
    previous.install_early()
    _patch_version_contract()
    _patch_qc()
    _start_worker()


__all__ = [
    "VERSION",
    "install_early",
    "_candidate_qc_v160",
    "_hard_structure_ok",
    "_patch_qc",
    "_patch_runtime",
    "_cmd_version",
]
