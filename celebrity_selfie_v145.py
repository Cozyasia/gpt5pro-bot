# -*- coding: utf-8 -*-
"""Celebrity Selfie v145: reliable public-person identity locking.

v144 fixed scene generation, but production showed the next bottleneck: OpenAI
could produce a structurally valid right-side person with very weak identity
similarity, while PiAPI was asked to run ``multi-face-swap`` on a one-face plate
whose long side could exceed the provider's documented image limit.

v145 keeps the v143/v144 fail-closed composition architecture and changes only
the public-person identity stage:

* PiAPI is attempted before generative OpenAI editing;
* one-face scene plates use PiAPI ``face-swap`` first, without unnecessary face
  indexes, and only then use indexed ``multi-face-swap`` as a compatibility
  fallback;
* both source and target images are normalised below 2048 px before submission;
* up to three ranked public-person references are tried independently;
* every returned image must still pass the strict one-face structure and Vision
  identity score before the user's original pixels are composited;
* OpenAI remains a final fallback and can make two targeted attempts;
* diagnostics expose provider, reference, task type, score and failure reason.
"""
from __future__ import annotations

import base64
import os
import time
from typing import Any

import celebrity_selfie_v139 as v139
import celebrity_selfie_v142 as v142
import celebrity_selfie_v143 as v143
import celebrity_selfie_v144 as v144

VERSION = "v145-piapi-celebrity-lock-retry-2026-07-21"
_GROUP = -2_100_000_800
_BUILDER_FLAG = "_celebrity_selfie_v145_builder"
_HANDLER_FLAG = "_celebrity_selfie_v145_handlers"

_ORIGINAL_V144_RUN = v144._run_v144_generation
_LAST_RUN_DEBUG: dict[str, Any] = {}


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"0", "false", "no", "off", ""}


def _number(name: str, default: float, minimum: float, maximum: float) -> float:
    return v139._number(name, default, minimum, maximum)


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    return v139._integer(name, default, minimum, maximum)


def _provider_order() -> list[str]:
    raw = os.environ.get("CELEBRITY_V145_CELEBRITY_PROVIDERS") or "piapi,openai"
    result: list[str] = []
    for item in raw.split(","):
        provider = item.strip().casefold()
        if provider in {"piapi", "openai"} and provider not in result:
            result.append(provider)
    return result or ["piapi", "openai"]


def _piapi_modes() -> list[str]:
    raw = os.environ.get("CELEBRITY_V145_PIAPI_MODES") or "face-swap,multi-face-swap"
    result: list[str] = []
    for item in raw.split(","):
        mode = item.strip().casefold()
        if mode in {"face-swap", "multi-face-swap"} and mode not in result:
            result.append(mode)
    return result or ["face-swap", "multi-face-swap"]


def _piapi_ready_image(raw: bytes, *, source: bool = False) -> bytes:
    configured = _integer("CELEBRITY_V145_PIAPI_MAX_SIDE", 1900, 1024, 2000)
    max_side = min(1600 if source else configured, 2000)
    return v139._jpeg(raw, max_side=max_side, quality=96)


def _piapi_request(mode: str, source: bytes, target: bytes) -> tuple[str, dict[str, Any]]:
    source_b64 = base64.b64encode(source).decode("ascii")
    target_b64 = base64.b64encode(target).decode("ascii")
    if mode == "face-swap":
        return "face-swap", {
            "swap_image": source_b64,
            "target_image": target_b64,
        }
    if mode == "multi-face-swap":
        return "multi-face-swap", {
            "swap_image": source_b64,
            "target_image": target_b64,
            "swap_faces_index": "0",
            "target_faces_index": "0",
        }
    raise ValueError(f"unsupported PiAPI face mode: {mode}")


async def _piapi_face_swap_once(mod: Any, target: bytes, reference: bytes, mode: str) -> bytes:
    source = _piapi_ready_image(v139._face_crop(reference, 1500), source=True)
    target_ready = _piapi_ready_image(target, source=False)
    task_type, inputs = _piapi_request(mode, source, target_ready)
    output = await v139.pi_identity._piapi_task(mod, task_type, inputs)
    return v139._jpeg(output, max_side=2000, quality=96)


def _identity_attempt(
    *,
    label: str,
    provider: str,
    reference_index: int,
    mode: str,
    score: float | None = None,
    status: str = "running",
    reason: str = "",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "stage": label,
        "provider": provider,
        "reference_index": reference_index,
        "mode": mode,
        "status": status,
    }
    if score is not None:
        row["score"] = round(float(score), 1)
    if reason:
        row["reason"] = reason[:500]
    return row


async def _celebrity_variants(
    mod: Any,
    plate: dict[str, Any],
    references: list[bytes],
    celebrity_name: str,
    aspect: str,
    debug: dict[str, Any],
) -> list[dict[str, Any]]:
    """Lock the public-person identity into the sole right-side plate face."""
    debug.setdefault("celebrity_lock_attempts", [])
    results: list[dict[str, Any]] = []
    minimum = _number(
        "CELEBRITY_V145_MIN_CELEBRITY_SCORE",
        _number("CELEBRITY_V143_MIN_CELEBRITY_SCORE", 66.0, 45.0, 92.0),
        45.0,
        92.0,
    )
    stop_score = _number("CELEBRITY_V145_STOP_SCORE", 80.0, minimum, 97.0)
    reference_limit = _integer("CELEBRITY_V145_PIAPI_REFERENCE_ATTEMPTS", 3, 1, 4)
    public_refs = [raw for raw in references if raw][:reference_limit]
    if not public_refs:
        return []

    for provider in _provider_order():
        accepted_before = len(results)

        if provider == "piapi":
            if not v139.pi_identity._piapi_key(mod):
                continue
            for reference_index, reference in enumerate(public_refs, start=1):
                for mode in _piapi_modes():
                    label = f"{plate['label']}_v145_celebrity_piapi_r{reference_index}_{mode.replace('-', '_')}"
                    stage = v139._stage_start(
                        debug,
                        label,
                        "piapi",
                        reference_index=reference_index,
                        task_type=mode,
                        max_side=_integer("CELEBRITY_V145_PIAPI_MAX_SIDE", 1900, 1024, 2000),
                    )
                    attempt = _identity_attempt(
                        label=label,
                        provider="piapi",
                        reference_index=reference_index,
                        mode=mode,
                    )
                    debug["celebrity_lock_attempts"].append(attempt)
                    try:
                        raw = await _piapi_face_swap_once(mod, plate["output"], reference, mode)
                        problem = v143._plate_problem(raw, label)
                        if problem:
                            raise v139.PipelineError("structural_qc", problem)
                        qc = await v143._single_face_identity_score(mod, raw, reference)
                        score = float(qc.get("score") or 0)
                        if qc.get("unknown") or score < minimum:
                            raise v139.PipelineError(
                                "celebrity_identity",
                                f"strict celebrity score {score:.1f} below {minimum:.1f}: {qc.get('reason')}",
                            )
                        row = {
                            "label": label,
                            "scene": plate["label"],
                            "scene_provider": plate["provider"],
                            "celebrity_provider": "piapi",
                            "celebrity_identity": round(score, 1),
                            "identity_unknown": False,
                            "reason": qc.get("reason"),
                            "reference_index": reference_index,
                            "piapi_task_type": mode,
                            "output": raw,
                        }
                        results.append(row)
                        debug["identity_candidates"].append({key: value for key, value in row.items() if key != "output"})
                        attempt.update(status="ok", score=round(score, 1), reason=str(qc.get("reason") or "ok")[:500])
                        v139._stage_finish(
                            stage,
                            "ok",
                            score=round(score, 1),
                            reference_index=reference_index,
                            task_type=mode,
                            bytes=len(raw),
                        )
                        if score >= stop_score:
                            break
                    except Exception as exc:
                        attempt.update(status="error", reason=v139._safe_error(exc)[:500])
                        v139._record_error(debug, stage, exc)
                if results and float(results[-1].get("celebrity_identity") or 0) >= stop_score:
                    break

        elif provider == "openai":
            if not v139.selfie._openai_key(mod):
                continue
            openai_attempts = _integer("CELEBRITY_V145_OPENAI_ATTEMPTS", 2, 1, 3)
            for attempt_index in range(openai_attempts):
                label = f"{plate['label']}_v145_celebrity_openai_{attempt_index + 1}"
                stage = v139._stage_start(
                    debug,
                    label,
                    "openai",
                    attempt=attempt_index + 1,
                    targeted_repair=bool(attempt_index),
                )
                attempt = _identity_attempt(
                    label=label,
                    provider="openai",
                    reference_index=1,
                    mode="high-fidelity-edit" if attempt_index == 0 else "targeted-repair",
                )
                debug["celebrity_lock_attempts"].append(attempt)
                try:
                    raw = await v139._openai_single_face(
                        mod,
                        plate["output"],
                        references[:3],
                        "right",
                        f"the selected PUBLIC PERSON ({celebrity_name})",
                        aspect,
                        repair=bool(attempt_index),
                    )
                    problem = v143._plate_problem(raw, label)
                    if problem:
                        raise v139.PipelineError("structural_qc", problem)
                    qc = await v143._single_face_identity_score(mod, raw, references[0])
                    score = float(qc.get("score") or 0)
                    if qc.get("unknown") or score < minimum:
                        raise v139.PipelineError(
                            "celebrity_identity",
                            f"strict celebrity score {score:.1f} below {minimum:.1f}: {qc.get('reason')}",
                        )
                    row = {
                        "label": label,
                        "scene": plate["label"],
                        "scene_provider": plate["provider"],
                        "celebrity_provider": "openai",
                        "celebrity_identity": round(score, 1),
                        "identity_unknown": False,
                        "reason": qc.get("reason"),
                        "openai_attempt": attempt_index + 1,
                        "output": raw,
                    }
                    results.append(row)
                    debug["identity_candidates"].append({key: value for key, value in row.items() if key != "output"})
                    attempt.update(status="ok", score=round(score, 1), reason=str(qc.get("reason") or "ok")[:500])
                    v139._stage_finish(stage, "ok", score=round(score, 1), bytes=len(raw))
                    if score >= stop_score:
                        break
                except Exception as exc:
                    attempt.update(status="error", reason=v139._safe_error(exc)[:500])
                    v139._record_error(debug, stage, exc)

        # A verified PiAPI result is preferred to further generative face editing.
        if len(results) > accepted_before:
            break

    results.sort(key=lambda item: float(item.get("celebrity_identity") or 0), reverse=True)
    return results[:3]


async def _run_v145_generation(
    mod: Any,
    user_photo: bytes,
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    previous_result: bytes | None = None,
    *,
    additional_user_refs: list[bytes] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    global _LAST_RUN_DEBUG
    started = time.time()
    try:
        output, debug = await _ORIGINAL_V144_RUN(
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
            "celebrity_lock_contract": "piapi-face-swap-first+under-2048+multi-reference+openai-fallback",
            "celebrity_provider_order": _provider_order(),
            "piapi_modes": _piapi_modes(),
            "v145_duration_s": round(time.time() - started, 2),
        })
        _LAST_RUN_DEBUG = debug
        v144._LAST_RUN_DEBUG = debug
        v143._LAST_RUN_DEBUG = debug
        v142._LAST_RUN_DEBUG = debug
        v139._LAST_RUN_DEBUG = debug
        return output, debug
    except Exception as exc:
        debug = dict(getattr(exc, "debug", None) or {})
        debug.update({
            "version": VERSION,
            "celebrity_lock_contract": "piapi-face-swap-first+under-2048+multi-reference+openai-fallback",
            "celebrity_provider_order": _provider_order(),
            "piapi_modes": _piapi_modes(),
            "v145_duration_s": round(time.time() - started, 2),
        })
        _LAST_RUN_DEBUG = debug
        v144._LAST_RUN_DEBUG = debug
        v143._LAST_RUN_DEBUG = debug
        v142._LAST_RUN_DEBUG = debug
        v139._LAST_RUN_DEBUG = debug
        if isinstance(exc, v139.PipelineError):
            exc.debug = debug
        raise


async def _run_compat(
    mod: Any,
    user_photo: bytes,
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    previous_result: bytes | None = None,
    *,
    additional_user_refs: list[bytes] | None = None,
) -> bytes:
    output, _ = await _run_v145_generation(
        mod,
        user_photo,
        celebrity_refs,
        celebrity_name,
        scene,
        previous_result=previous_result,
        additional_user_refs=additional_user_refs,
    )
    return output


def _patch_version_contract() -> None:
    try:
        import neyrobot_prod
        from neyrobot_prod import bootstrap, versioning

        neyrobot_prod.VERSION = VERSION
        bootstrap.VERSION = VERSION
        versioning.VERSION = VERSION
    except Exception:
        pass


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    session = v139.selfie.engine._session(context, create=False) or {}
    debug = session.get("v142_debug") or _LAST_RUN_DEBUG or v144._LAST_RUN_DEBUG or {}
    selected = debug.get("selected") or {}
    lines = [
        f"📸 Celebrity Selfie / {VERSION}",
        "architecture=strict_preserve_user+provider_safe_scene+piapi_first_identity_lock",
        "user_face_generation=disabled",
        "celebrity_provider_order=piapi,openai",
        "piapi_primary_task=face-swap",
        "piapi_fallback_task=multi-face-swap",
        f"piapi_max_side={_integer('CELEBRITY_V145_PIAPI_MAX_SIDE', 1900, 1024, 2000)}",
        f"reference_attempts={_integer('CELEBRITY_V145_PIAPI_REFERENCE_ATTEMPTS', 3, 1, 4)}",
        f"run_id={debug.get('run_id') or '-'}",
        f"state={session.get('state') or '-'}",
        f"scene_candidates={len(debug.get('scene_candidates') or [])}",
        f"celebrity_candidates={len(debug.get('identity_candidates') or [])}",
        f"composite_candidates={len(debug.get('composite_candidates') or [])}",
        f"celebrity_lock_attempts={str(debug.get('celebrity_lock_attempts') or '-')[:2400]}",
        f"delivery_mode={session.get('delivery_mode') or '-'}",
        f"selected={str(selected or '-')[:1600]}",
        f"failure_class={debug.get('failure_class') or '-'}",
        f"last_error={session.get('last_generation_error') or '-'}",
    ]
    errors = debug.get("errors") or []
    if errors:
        lines.append("errors:")
        for item in errors[-10:]:
            lines.append(f"- {item.get('stage')} [{item.get('provider')}]: {str(item.get('error') or '')[:360]}")
    text = "\n".join(lines)
    for offset in range(0, len(text), 3900):
        await update.effective_message.reply_text(text[offset:offset + 3900])
    raise ApplicationHandlerStop


def install() -> None:
    os.environ.setdefault("CELEBRITY_V145_CELEBRITY_PROVIDERS", "piapi,openai")
    os.environ.setdefault("CELEBRITY_V145_PIAPI_MODES", "face-swap,multi-face-swap")
    os.environ.setdefault("CELEBRITY_V145_PIAPI_REFERENCE_ATTEMPTS", "3")
    os.environ.setdefault("CELEBRITY_V145_PIAPI_MAX_SIDE", "1900")
    os.environ.setdefault("CELEBRITY_V145_OPENAI_ATTEMPTS", "2")
    os.environ.setdefault("CELEBRITY_V145_STOP_SCORE", "80")
    os.environ["CELEBRITY_V143_LEGACY_FALLBACK"] = "0"

    v143._celebrity_variants = _celebrity_variants
    v142._celebrity_variants = _celebrity_variants
    v139.selfie._run_v145_generation = _run_v145_generation
    v139.selfie.engine._run_multi_reference_generation = _run_compat
    v139.selfie.engine._diag = _diag
    _patch_version_contract()


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        install()
        if not getattr(app, _HANDLER_FLAG, False):
            for command in (
                "diag_selfie_v145",
                "diag_selfie_v144",
                "diag_selfie_v143",
                "diag_selfie_v142",
                "diag_selfie_v141",
                "diag_selfie_v139",
                "diag_celebrity_flow",
                "diag_brand",
            ):
                app.add_handler(CommandHandler(command, _diag), group=_GROUP)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


def install_early() -> None:
    install()
    install_builder_hook()


__all__ = [
    "VERSION",
    "install",
    "install_early",
    "install_builder_hook",
    "_provider_order",
    "_piapi_modes",
    "_piapi_ready_image",
    "_piapi_request",
    "_piapi_face_swap_once",
    "_celebrity_variants",
    "_run_v145_generation",
    "_diag",
]
