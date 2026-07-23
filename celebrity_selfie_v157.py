# -*- coding: utf-8 -*-
"""Celebrity Selfie v157: restore the catalog/scene wizard and tighten identity.

v156 already produces a coherent scene and preserves the user's appearance well.
This overlay leaves that render architecture intact. It restores the audited
v124 Telegram wizard in front of all generic photo routers and makes the
selected public figure the dominant acceptance criterion.
"""
from __future__ import annotations

import contextlib
import logging
import os
from typing import Any

import celebrity_selfie_v124 as flow
import celebrity_selfie_v139 as v139
import celebrity_selfie_v156 as base

VERSION = "v157-menu-selected-identity-lock-2026-07-23"
_GROUP = -2_100_003_000
_BUILDER_FLAG = "_celebrity_selfie_v157_builder"
_HANDLER_FLAG = "_celebrity_selfie_v157_handlers"
_INSTALL_FLAG = "_celebrity_selfie_v157_installed"

log = logging.getLogger("gpt-bot.celebrity-selfie-v157")
_BASE_SCENE_PROMPT = base._scene_prompt
_BASE_CANDIDATE_QC = base._candidate_qc
_BASE_GENERATE = base._generate


def _number(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(str(os.environ.get(name) or default).replace(",", "."))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _selected_entry(session: dict[str, Any]) -> dict[str, Any] | None:
    with contextlib.suppress(Exception):
        entry = v139.selfie.engine._selected_entry(session)
        if isinstance(entry, dict):
            return entry
    return None


def _lock_selected_person(session: dict[str, Any]) -> dict[str, Any] | None:
    """Make the catalog selection authoritative over free-form prompt wording."""
    entry = _selected_entry(session)
    if not entry:
        return None
    name = str(entry.get("display_name") or entry.get("name") or "").strip()
    celeb_id = str(entry.get("id") or "").strip()
    if name:
        session["celebrity_name"] = name
        session["selected_celebrity_name"] = name
    if celeb_id:
        session["selected_celebrity_id"] = celeb_id
    session["celebrity_identity_source"] = "catalog"
    session["celebrity_selection_locked"] = True
    return entry


def _scene_prompt(celebrity_name: str, scene: str, aspect: str, variant: int) -> str:
    prompt = _BASE_SCENE_PROMPT(celebrity_name, scene, aspect, variant)
    return (
        prompt
        + " IDENTITY PRIORITY: the RIGHT person must be the exact same individual shown in all PUBLIC FIGURE REFERENCES, "
        + f"not merely a person of similar age or style and not a generic look-alike for {celebrity_name}. "
        + "Cross-check stable geometry across the public references: skull and forehead proportions, hairline, brow shape, "
        + "eye spacing and eyelids, nose bridge and tip, cheek structure, lips, jaw, ears, facial-hair pattern and natural age. "
        + "Use the references as one identity set. When appearance differs between references, preserve the repeated stable traits. "
        + "Do not borrow the face of another public person and do not average the public identity with the user. "
        + "The left USER identity, requested scene, camera position, lighting and natural realism remain equally mandatory."
    )


async def _candidate_qc(
    mod: Any,
    raw: bytes,
    user_ref: bytes,
    celebrity_ref: bytes,
    scene: str,
    debug: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    result = await _BASE_CANDIDATE_QC(mod, raw, user_ref, celebrity_ref, scene, debug, label)
    user_score = float(result.get("user_similarity") or 0)
    celebrity_score = float(result.get("celebrity_similarity") or 0)
    face_quality = float(result.get("face_quality") or 0)
    overall_quality = float(result.get("quality") or 0)
    min_user = _number("CELEBRITY_V157_MIN_USER_SIMILARITY", 64, 45, 92)
    min_celebrity = _number("CELEBRITY_V157_MIN_CELEBRITY_SIMILARITY", 78, 55, 94)
    identity_known = not bool(result.get("unknown"))

    # The selected public figure now dominates ranking. A beautiful scene with a
    # generic look-alike must never outrank a slightly less polished but accurate
    # identity match. The user's successful v156 transfer remains protected.
    total = (
        user_score * 0.25
        + celebrity_score * 0.55
        + face_quality * 0.08
        + overall_quality * 0.12
    )
    result["total"] = round(total, 2)
    result["celebrity_identity_gate"] = round(min_celebrity, 1)
    result["user_identity_gate"] = round(min_user, 1)
    result["selected_identity_locked"] = True
    result["accepted"] = bool(
        result.get("accepted")
        and identity_known
        and user_score >= min_user
        and celebrity_score >= min_celebrity
    )
    if celebrity_score < min_celebrity:
        reason = str(result.get("reason") or "")
        result["reason"] = (
            f"selected-public-figure similarity {celebrity_score:.0f} is below required {min_celebrity:.0f}; "
            + reason
        )[:420]
    return result


async def _generate(update: Any, context: Any, *, refinement: bool = False) -> None:
    session = v139.selfie.engine._session(context, create=False)
    if session:
        entry = _lock_selected_person(session)
        if entry:
            session["identity_reference_policy"] = "selected-catalog-person-only"
    await _BASE_GENERATE(update, context, refinement=refinement)


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
    debug = session.get("v156_debug") or session.get("v139_debug") or base._LAST_RUN_DEBUG or {}
    selected = debug.get("selected") or {}
    entry = _selected_entry(session) or {}
    lines = [
        f"📸 Celebrity Selfie / {VERSION}",
        "menu_owner=v124-exclusive-catalog-wizard",
        "entry_callbacks=act:fun:aiselfie,pedit:aiselfie",
        "generic_nano_banana_free_prompt=blocked_during_wizard",
        "user_photo_then_celebrity_menu=required",
        "selected_person_then_scene_menu=required",
        "render_base=v156-comet-dual-identity-best-of-n",
        "user_transfer=v156-unchanged",
        "scene_generation=v156-unchanged",
        "selected_public_identity=dominant-ranking-and-hard-gate",
        f"state={session.get('state') or '-'}",
        f"selected_id={session.get('selected_celebrity_id') or entry.get('id') or '-'}",
        f"selected_name={session.get('selected_celebrity_name') or entry.get('display_name') or '-'}",
        f"reference_count={debug.get('selected_reference_count') or 0}",
        f"user_similarity={selected.get('user_identity', '-')}",
        f"celebrity_similarity={selected.get('celebrity_identity', '-')}",
        f"celebrity_gate={os.environ.get('CELEBRITY_V157_MIN_CELEBRITY_SIMILARITY', '78')}",
        f"quality={selected.get('quality', '-')}",
        f"failure_class={debug.get('failure_class') or '-'}",
        f"last_error={session.get('last_generation_error') or '-'}",
    ]
    await update.effective_message.reply_text("\n".join(lines)[:3900])
    raise ApplicationHandlerStop


def install() -> None:
    engine = v139.selfie.engine
    if getattr(engine, _INSTALL_FLAG, False):
        _patch_version_contract()
        return

    # Keep the successful v156 scene/user architecture. Only selection routing,
    # prompt identity emphasis, acceptance and ranking are changed.
    os.environ["CELEBRITY_V156_MIN_USER_SIMILARITY"] = os.environ.get(
        "CELEBRITY_V157_MIN_USER_SIMILARITY", "64"
    )
    os.environ["CELEBRITY_V156_MIN_CELEBRITY_SIMILARITY"] = os.environ.get(
        "CELEBRITY_V157_MIN_CELEBRITY_SIMILARITY", "78"
    )
    os.environ.setdefault("CELEBRITY_V157_MIN_USER_SIMILARITY", "64")
    os.environ.setdefault("CELEBRITY_V157_MIN_CELEBRITY_SIMILARITY", "78")
    os.environ.setdefault("CELEBRITY_V156_CELEBRITY_REFERENCE_LIMIT", "3")
    os.environ.setdefault("CELEBRITY_V156_CANDIDATES", "3")
    os.environ.setdefault("CELEBRITY_V156_TARGETED_REPAIR", "1")

    base.install()
    base.VERSION = VERSION
    base._scene_prompt = _scene_prompt
    base._candidate_qc = _candidate_qc
    v139.VERSION = VERSION
    v139._generate = _generate
    v139.selfie._generate = _generate
    engine._generate = _generate
    engine._diag = _diag
    # v124 delegates all menu, celebrity and scene callbacks to this shared v122
    # engine object. Re-assert v156's callback owner after the menu hook is loaded.
    engine._on_callback = base._on_callback
    setattr(engine, _INSTALL_FLAG, True)
    _patch_version_contract()
    log.info("installed %s menu=v124 render=v156 celebrity_gate=%s", VERSION, os.environ["CELEBRITY_V157_MIN_CELEBRITY_SIMILARITY"])


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return

    # This is the key routing correction: v124 owns callback/photo/text at group
    # -20000, before the generic Photo Workshop/Nano Banana handlers.
    flow.install_builder_hook()
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        install()
        app = original_build(self, *args, **kwargs)
        if not getattr(app, _HANDLER_FLAG, False):
            for command in (
                "diag_selfie_v157",
                "diag_selfie_v156",
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
    "_lock_selected_person",
    "_scene_prompt",
    "_candidate_qc",
    "_generate",
    "_diag",
]
