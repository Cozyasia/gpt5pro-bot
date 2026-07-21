# -*- coding: utf-8 -*-
"""Celebrity Selfie v152: empty Comet plate contract hotfix.

v151 correctly changed the scene generator from a one-person plate to an empty,
composition-ready Comet location plate.  The historical v143 orchestrator still
re-validated every returned plate with its original "exactly one foreground
face" rule.  Therefore valid v151 scenes containing zero foreground faces were
rejected after generation.

v152 makes the contract consistent end to end: Comet background labels are
validated by the composition-ready gate, while all historical one-person plate
labels continue through the strict legacy validator.  Identity and final output
remain source-pixel-only with the existing v149 visible-layer proofs.
"""
from __future__ import annotations

import time
from typing import Any

import celebrity_selfie_v139 as v139
import celebrity_selfie_v142 as v142
import celebrity_selfie_v143 as v143
import celebrity_selfie_v147 as v147
import celebrity_selfie_v149 as v149
import celebrity_selfie_v150 as v150
import celebrity_selfie_v151 as v151

VERSION = "v152-empty-comet-plate-contract-2026-07-21"
_GROUP = -2_100_001_500
_BUILDER_FLAG = "_celebrity_selfie_v152_builder"
_HANDLER_FLAG = "_celebrity_selfie_v152_handlers"
_LAST_RUN_DEBUG: dict[str, Any] = {}


def _is_empty_scene_label(label: str) -> bool:
    value = str(label or "").strip().casefold()
    return any(
        marker in value
        for marker in (
            "v150_background_comet_",
            "v151_background_comet_",
            "v152_background_comet_",
        )
    )


def _composition_aware_plate_problem(raw: bytes, label: str) -> str:
    """Apply the correct structural contract for each plate architecture."""
    if _is_empty_scene_label(label):
        problem, _details = v151._composition_ready_problem(raw)
        return problem
    return v147._background_aware_plate_problem(raw, label)


async def _run_v152_generation(
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
    contract = {
        "version": VERSION,
        "architecture": "empty-comet-scene+verified-visible-dual-source-layers",
        "empty_scene_plate_gate": "composition-ready",
        "legacy_one_face_plate_gate": "disabled-for-comet-backgrounds",
        "scene_provider_order": ["comet"],
        "user_face_generation": "disabled",
        "celebrity_face_generation": "disabled",
        "face_swap": "disabled",
        "credit_charge_on_failure": False,
    }
    try:
        output, debug = await v151._run_v151_generation(
            mod,
            user_photo,
            celebrity_refs,
            celebrity_name,
            scene,
            previous_result=previous_result,
            additional_user_refs=additional_user_refs,
        )
        debug = dict(debug or {})
        debug.update(contract)
        debug["v152_duration_s"] = round(time.time() - started, 2)
        _LAST_RUN_DEBUG = debug
        for module in (v151, v150, v149, v147, v143, v142, v139):
            module._LAST_RUN_DEBUG = debug
        return output, debug
    except Exception as exc:
        debug = dict(getattr(exc, "debug", None) or {})
        debug.update(contract)
        debug["v152_duration_s"] = round(time.time() - started, 2)
        _LAST_RUN_DEBUG = debug
        for module in (v151, v150, v149, v147, v143, v142, v139):
            module._LAST_RUN_DEBUG = debug
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
    output, _ = await _run_v152_generation(
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
    debug = session.get("v142_debug") or session.get("v139_debug") or _LAST_RUN_DEBUG or {}
    lines = [
        f"📸 Celebrity Selfie / {VERSION}",
        "architecture=empty_comet_scene+verified_visible_dual_source_layers",
        "scene_provider_order=comet",
        f"comet={'ready' if bool(v150._comet_key()) else 'missing'}",
        f"comet_model={v151._comet_model()}",
        "empty_scene_plate_gate=composition_ready",
        "legacy_one_face_plate_gate=disabled_for_comet_backgrounds",
        "gemini_scene=disabled",
        "flux_scene=disabled",
        "local_placeholder_background=disabled",
        "user_face_generation=disabled",
        "celebrity_face_generation=disabled",
        "face_swap=disabled",
        f"run_id={debug.get('run_id') or '-'}",
        f"state={session.get('state') or '-'}",
        f"scene_candidates={len(debug.get('scene_candidates') or [])}",
        f"celebrity_candidates={len(debug.get('identity_candidates') or [])}",
        f"composite_candidates={len(debug.get('composite_candidates') or [])}",
        f"background_attempts={str(debug.get('background_attempts') or '-')[:1800]}",
        f"selected={str(debug.get('selected') or '-')[:900]}",
        f"failure_class={debug.get('failure_class') or '-'}",
        f"last_error={session.get('last_generation_error') or '-'}",
    ]
    for item in (debug.get("errors") or [])[-6:]:
        lines.append(
            f"- {item.get('stage')} [{item.get('provider')}]: "
            f"{str(item.get('error') or '')[:300]}"
        )
    text = "\n".join(lines)
    for offset in range(0, len(text), 3900):
        await update.effective_message.reply_text(text[offset:offset + 3900])
    raise ApplicationHandlerStop


def install() -> None:
    v151.install()

    # v143 owns the orchestration loop and performs a second plate validation
    # after v151's Comet builder returns. Override that exact live symbol.
    v143._plate_problem = _composition_aware_plate_problem

    v139.selfie._run_v152_generation = _run_v152_generation
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
                "diag_selfie_v152",
                "diag_selfie_v151",
                "diag_selfie_v150",
                "diag_selfie_v149",
                "diag_selfie_v148",
                "diag_selfie_v147",
                "diag_selfie_v146",
                "diag_selfie_v145",
                "diag_selfie_v144",
                "diag_selfie_v143",
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
    "_is_empty_scene_label",
    "_composition_aware_plate_problem",
    "_run_v152_generation",
    "_diag",
]
