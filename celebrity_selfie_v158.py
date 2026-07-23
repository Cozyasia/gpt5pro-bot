# -*- coding: utf-8 -*-
"""Celebrity Selfie v158: repository-pinned Roman Abramovich references.

The complete v157 catalog/scene wizard and v156 coherent Comet renderer remain
unchanged. This overlay only replaces the reference source for the selected
catalog entry ``ru_roman_abramovich`` with three owner-provided portraits.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any

import celebrity_selfie_v124 as flow
import celebrity_selfie_v139 as v139
import celebrity_selfie_v156 as renderer
import celebrity_selfie_v157 as previous

VERSION = "v158-fixed-roman-reference-pack-2026-07-23"
_GROUP = -2_100_004_000
_BUILDER_FLAG = "_celebrity_selfie_v158_builder"
_HANDLER_FLAG = "_celebrity_selfie_v158_handlers"
_INSTALL_FLAG = "_celebrity_selfie_v158_installed"

ROMAN_ID = "ru_roman_abramovich"
ROMAN_NAME = "Роман Абрамович"
_ROOT = Path(__file__).resolve().parent
_PACK_ROOT = _ROOT / "celebrity_library" / "fixed_refs" / ROMAN_ID
_CACHE_ROOT = Path(os.environ.get("CELEBRITY_FIXED_REF_CACHE") or "/tmp/neyrobot_fixed_refs") / ROMAN_ID
_PACK_FILES = (
    "01_front_current.jpg.b64",
    "02_three_quarter_current.jpg.b64",
    "03_front_warm_current.jpg.b64",
)
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/=]{32,}")

log = logging.getLogger("gpt-bot.celebrity-selfie-v158")
_ORIGINAL_REFERENCE_PATHS = v139.selfie.engine._reference_paths
_ORIGINAL_PREPARE_LIBRARY_REFS = getattr(v139.selfie.engine, "_prepare_library_refs", None)
_ORIGINAL_RANK_REFERENCES = renderer._rank_celebrity_references
_CALLBACK_TARGET: Any | None = None


def _normalise_name(value: Any) -> str:
    return str(value or "").strip().casefold().replace("ё", "е")


def _is_roman_session(session: dict[str, Any] | None) -> bool:
    if not isinstance(session, dict):
        return False
    if ROMAN_ID in {
        str(session.get("selected_celebrity_id") or "").strip(),
        str(session.get("celebrity_id") or "").strip(),
    }:
        return True
    entry = None
    with contextlib.suppress(Exception):
        entry = v139.selfie.engine._selected_entry(session)
    if isinstance(entry, dict) and str(entry.get("id") or "").strip() == ROMAN_ID:
        return True
    names = {
        _normalise_name(session.get("selected_celebrity_name")),
        _normalise_name(session.get("celebrity_name")),
        _normalise_name((entry or {}).get("display_name") if isinstance(entry, dict) else ""),
    }
    return _normalise_name(ROMAN_NAME) in names


def _valid_jpeg(raw: bytes) -> bool:
    return bool(
        len(raw) >= 15_000
        and raw.startswith(b"\xff\xd8\xff")
        and raw.endswith(b"\xff\xd9")
    )


def _decode_asset_text(text: str, label: str = "asset") -> bytes:
    """Recover one complete JPEG from a textual standard-base64 asset.

    Historical PR tooling could append display material after a correctly padded
    payload. Candidate decoding therefore stops at the first padding boundary and
    accepts a result only when it is a complete JPEG. Invalid/truncated data still
    fails startup before a paid generation can begin.
    """
    runs = _BASE64_RUN.findall(text or "")
    if not runs:
        raise ValueError(f"no base64 payload in {label}")

    candidates: list[str] = []
    joined = "".join(runs)
    for value in (joined, *runs):
        if not value:
            continue
        variants = [value]
        pad_at = value.find("=")
        if pad_at >= 0:
            end = pad_at + 1
            while end < len(value) and value[end] == "=":
                end += 1
            variants.insert(0, value[:end])
        for candidate in variants:
            if candidate and candidate not in candidates:
                candidates.append(candidate)

    errors: list[str] = []
    for candidate in candidates:
        payload = candidate
        if "=" not in payload and len(payload) % 4:
            payload += "=" * (-len(payload) % 4)
        try:
            raw = base64.b64decode(payload, validate=True)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}:{exc}")
            continue
        if _valid_jpeg(raw):
            return raw
        errors.append(f"decoded-not-complete-jpeg:{len(raw)}")
    raise ValueError(f"invalid or truncated JPEG asset {label}: {'; '.join(errors[-4:])}")


def _decode_reference(source: Path, target: Path) -> Path:
    if not source.is_file():
        raise FileNotFoundError(f"fixed reference missing: {source}")
    raw = _decode_asset_text(source.read_text(encoding="ascii"), source.name)
    digest = hashlib.sha256(raw).hexdigest()
    digest_path = target.with_suffix(target.suffix + ".sha256")
    cached_ok = (
        target.exists()
        and target.stat().st_size == len(raw)
        and digest_path.exists()
        and digest_path.read_text(encoding="ascii").strip() == digest
    )
    if not cached_ok:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        digest_path.write_text(digest, encoding="ascii")
    return target


def _fixed_reference_paths() -> list[str]:
    _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    result = [
        str(_decode_reference(_PACK_ROOT / filename, _CACHE_ROOT / f"{index:02d}.jpg"))
        for index, filename in enumerate(_PACK_FILES, start=1)
    ]
    if len(result) != 3:
        raise RuntimeError("Roman reference pack must contain exactly three images")
    return result


def _fixed_reference_bytes() -> list[bytes]:
    return [Path(path).read_bytes() for path in _fixed_reference_paths()]


def _reference_paths(session: dict[str, Any]) -> list[str]:
    if _is_roman_session(session):
        try:
            paths = _fixed_reference_paths()
            session["fixed_reference_pack"] = "roman-abramovich-owner-pack-v1"
            session["fixed_reference_count"] = len(paths)
            session["celebrity_identity_source"] = "repository-fixed-pack"
            session["identity_reference_policy"] = "repository-fixed-pack-only"
            return paths
        except Exception as exc:
            session["fixed_reference_error"] = f"{type(exc).__name__}: {exc}"[:500]
            log.exception("Roman fixed-reference materialisation failed")
    return list(_ORIGINAL_REFERENCE_PATHS(session) or [])


async def _prepare_library_refs(update: Any, context: Any, entry: dict[str, Any]) -> None:
    celeb_id = str((entry or {}).get("id") or "").strip()
    if celeb_id != ROMAN_ID:
        if callable(_ORIGINAL_PREPARE_LIBRARY_REFS):
            await _ORIGINAL_PREPARE_LIBRARY_REFS(update, context, entry)
            return
        raise RuntimeError("catalog reference preparation is unavailable")

    session = v139.selfie.engine._session(context)
    paths = _fixed_reference_paths()
    locked_entry = dict(entry or {})
    locked_entry.setdefault("id", ROMAN_ID)
    locked_entry.setdefault("display_name", ROMAN_NAME)
    session.update({
        "selected_celebrity_id": ROMAN_ID,
        "celebrity_id": ROMAN_ID,
        "selected_celebrity_name": ROMAN_NAME,
        "celebrity_name": ROMAN_NAME,
        "selected_entry": locked_entry,
        "selected_celebrity": locked_entry,
        "celebrity_entry": locked_entry,
        "celebrity_selection_locked": True,
        "celebrity_identity_source": "repository-fixed-pack",
        "identity_reference_policy": "repository-fixed-pack-only",
        "fixed_reference_pack": "roman-abramovich-owner-pack-v1",
        "fixed_reference_count": len(paths),
        "fixed_reference_paths": paths,
        "reference_paths": paths,
        "celebrity_reference_paths": paths,
        "library_reference_paths": paths,
        "state": "await_scene",
    })
    await update.effective_message.reply_text(
        "✅ Выбран: Роман Абрамович.\n"
        "Использую закреплённый набор из 3 референсов, приложенных владельцем проекта. "
        "Теперь выберите или опишите сцену.",
        reply_markup=v139.selfie.engine._scene_kb(),
    )


async def _v122_callback_without_false_error(update: Any, context: Any) -> Any:
    target = _CALLBACK_TARGET
    if not callable(target):
        raise RuntimeError("Celebrity Selfie callback target is unavailable")
    try:
        return await target(update, context)
    except Exception as exc:
        try:
            from telegram.ext import ApplicationHandlerStop
        except Exception:
            ApplicationHandlerStop = ()  # type: ignore[assignment]
        if ApplicationHandlerStop and isinstance(exc, ApplicationHandlerStop):
            return None
        raise


def _hashes(items: list[bytes]) -> set[str]:
    return {hashlib.sha256(raw).hexdigest() for raw in items if raw}


async def _rank_celebrity_references(mod: Any, refs: list[bytes], debug: dict[str, Any]) -> list[bytes]:
    try:
        fixed = _fixed_reference_bytes()
        if len(refs) >= 3 and _hashes(fixed).issubset(_hashes(refs)):
            debug["reference_source"] = "repository-fixed-pack"
            debug["reference_pack"] = "roman-abramovich-owner-pack-v1"
            debug["reference_local_ranking"] = [
                {"source_index": index, "score": 100.0, "faces": 1, "fixed": True}
                for index in range(1, len(fixed) + 1)
            ]
            debug["reference_vision_qc"] = [
                {"source_index": index, "accepted": True, "identity_usefulness": 100.0, "reason": "owner-pinned"}
                for index in range(1, len(fixed) + 1)
            ]
            return fixed
    except Exception as exc:
        debug.setdefault("reference_errors", []).append(f"fixed-pack:{type(exc).__name__}:{exc}"[:500])
    return await _ORIGINAL_RANK_REFERENCES(mod, refs, debug)


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
    debug = session.get("v156_debug") or session.get("v139_debug") or renderer._LAST_RUN_DEBUG or {}
    selected = debug.get("selected") or {}
    fixed_paths: list[str] = []
    fixed_error = ""
    try:
        fixed_paths = _fixed_reference_paths()
    except Exception as exc:
        fixed_error = f"{type(exc).__name__}: {exc}"
    lines = [
        f"📸 Celebrity Selfie / {VERSION}",
        "menu_owner=v124-exclusive-catalog-wizard",
        "false_submenu_error=removed",
        "render_base=v156-comet-dual-identity-best-of-n",
        "user_transfer=v156-unchanged",
        "scene_generation=v156-unchanged",
        "roman_reference_source=repository-fixed-pack",
        f"roman_reference_count={len(fixed_paths)}",
        f"roman_reference_pack={'ready' if len(fixed_paths) == 3 else 'error'}",
        f"roman_reference_error={fixed_error or '-'}",
        f"state={session.get('state') or '-'}",
        f"selected_id={session.get('selected_celebrity_id') or '-'}",
        f"selected_name={session.get('selected_celebrity_name') or '-'}",
        f"active_reference_source={debug.get('reference_source') or session.get('celebrity_identity_source') or '-'}",
        f"active_reference_count={debug.get('selected_reference_count') or session.get('fixed_reference_count') or 0}",
        f"user_similarity={selected.get('user_identity', '-')}",
        f"celebrity_similarity={selected.get('celebrity_identity', '-')}",
        f"quality={selected.get('quality', '-')}",
        f"failure_class={debug.get('failure_class') or '-'}",
        f"last_error={session.get('last_generation_error') or '-'}",
    ]
    await update.effective_message.reply_text("\n".join(lines)[:3900])
    raise ApplicationHandlerStop


def install() -> None:
    global _CALLBACK_TARGET
    engine = v139.selfie.engine
    if getattr(engine, _INSTALL_FLAG, False):
        _patch_version_contract()
        return
    previous.install()
    os.environ.setdefault("CELEBRITY_V158_MIN_CELEBRITY_SIMILARITY", "74")
    os.environ["CELEBRITY_V157_MIN_CELEBRITY_SIMILARITY"] = os.environ.get(
        "CELEBRITY_V158_MIN_CELEBRITY_SIMILARITY", "74"
    )
    os.environ["CELEBRITY_V156_MIN_CELEBRITY_SIMILARITY"] = os.environ.get(
        "CELEBRITY_V158_MIN_CELEBRITY_SIMILARITY", "74"
    )
    os.environ.setdefault("CELEBRITY_V156_CELEBRITY_REFERENCE_LIMIT", "3")
    os.environ.setdefault("CELEBRITY_V156_CANDIDATES", "3")
    _fixed_reference_paths()  # fail at deploy/start, never during a paid job

    current_callback = flow.base._on_callback
    if current_callback is not _v122_callback_without_false_error:
        _CALLBACK_TARGET = current_callback
    flow.base._on_callback = _v122_callback_without_false_error
    flow.base._prepare_library_refs = _prepare_library_refs
    engine._prepare_library_refs = _prepare_library_refs
    engine._reference_paths = _reference_paths
    renderer._rank_celebrity_references = _rank_celebrity_references
    previous.VERSION = VERSION
    renderer.VERSION = VERSION
    v139.VERSION = VERSION
    engine._diag = _diag
    setattr(engine, _INSTALL_FLAG, True)
    _patch_version_contract()
    log.info("installed %s fixed_pack=%s refs=3", VERSION, ROMAN_ID)


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return
    install()
    previous.install_builder_hook()
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        install()
        app = original_build(self, *args, **kwargs)
        if not getattr(app, _HANDLER_FLAG, False):
            for command in (
                "diag_selfie_v158", "diag_selfie_v157", "diag_selfie_v156",
                "diag_celebrity_flow", "diag_brand",
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
    "VERSION", "ROMAN_ID", "ROMAN_NAME", "install", "install_early",
    "install_builder_hook", "_fixed_reference_paths", "_reference_paths",
    "_prepare_library_refs", "_rank_celebrity_references", "_diag",
    "_decode_asset_text",
]
