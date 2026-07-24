# -*- coding: utf-8 -*-
"""Neyro-Bot v162: one authoritative Celebrity Selfie wizard.

This release keeps the v161 Roman hybrid identity renderer, v159 payments and
v120 medical stack intact.  It only fixes conversation ownership:

* every AI-selfie entry opens the catalog wizard before legacy photo tools;
* a user photo can never fall through to the generic ``Фото получено`` router
  while this wizard is active;
* a public person/character is mandatory before a scene can render;
* menu selection and free-text requests share the same catalog/reference path;
* catalog entries automatically use their fetched reference pack, while Roman
  Abramovich always uses the owner-pinned pack and v161 hybrid renderer;
* /version has exactly one handler and no duplicate generic error card.
"""
from __future__ import annotations

import contextlib
import logging
import os
import re
import threading
import time
from typing import Any

from . import hotfix_v161 as previous

import celebrity_selfie_v122 as engine
import celebrity_selfie_v123 as legacy_flow
import celebrity_selfie_v124 as wizard

VERSION = "v162-unified-celebrity-selfie-flow-2026-07-24"
_GROUP = -2_146_000_000
_BUILDER_FLAG = "_neyrobot_v162_builder"
_HANDLER_FLAG = "_neyrobot_v162_handlers"
_WORKER_STARTED = False
_LOCK = threading.RLock()
log = logging.getLogger("gpt-bot.hotfix-v162")

# The generic Comet edit route remains a fallback for non-catalog legacy calls,
# but it must have enough time to return instead of failing at the old short cap.
os.environ.setdefault("COMET_IMAGE_EDIT_TIMEOUT_S", "600")
os.environ.setdefault("CELEBRITY_V150_COMET_TIMEOUT_S", "600")

_SELFIE_WORDS = (
    "ai-селфи", "ai selfie", "селфи", "selfie", "фото со", "фото с",
    "сделай", "создай", "сгенерируй", "пожалуйста",
)
_SCENE_ONLY_WORDS = {
    "в", "на", "у", "около", "рядом", "со", "с", "и", "мне", "меня",
    "ним", "ней", "этим", "этой", "известным", "известной", "человеком",
    "персонажем", "героем", "актёром", "актером", "артистом", "звездой",
}


def _stop() -> None:
    from telegram.ext import ApplicationHandlerStop
    raise ApplicationHandlerStop


def _normalise(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("ё", "е").split())


def _session(context: Any, create: bool = True) -> dict[str, Any] | None:
    return engine._session(context, create=create)


def _active(context: Any) -> bool:
    return bool(wizard._is_active(context))


def _selected_entry(session: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(session, dict):
        return None
    with contextlib.suppress(Exception):
        entry = engine._selected_entry(session)
        if isinstance(entry, dict):
            return entry
    for key in ("selected_entry", "selected_celebrity", "celebrity_entry"):
        entry = session.get(key)
        if isinstance(entry, dict):
            return entry
    return None


def _selected_target(session: dict[str, Any] | None) -> tuple[str, str]:
    if not isinstance(session, dict):
        return "", ""
    entry = _selected_entry(session) or {}
    target_id = str(
        session.get("selected_celebrity_id")
        or session.get("celebrity_id")
        or entry.get("id")
        or ""
    ).strip()
    target_name = str(
        session.get("selected_celebrity_name")
        or session.get("celebrity_name")
        or entry.get("display_name")
        or entry.get("name")
        or ""
    ).strip()
    return target_id, target_name


def _target_ready(session: dict[str, Any] | None) -> bool:
    target_id, target_name = _selected_target(session)
    if target_id or target_name:
        return True
    if not isinstance(session, dict):
        return False
    # User-supplied character references are also a valid explicit target.
    paths = session.get("reference_paths") or session.get("celebrity_reference_paths") or []
    return bool(paths and session.get("custom_celebrity_name"))


def _catalog_values(item: dict[str, Any]) -> list[str]:
    return [
        str(item.get("display_name") or ""),
        str(item.get("sort_name") or ""),
        *[str(value) for value in (item.get("aliases") or [])],
    ]


def _catalog_match(text: str) -> dict[str, Any] | None:
    normalized = _normalise(text)
    if not normalized:
        return None
    with contextlib.suppress(Exception):
        direct = legacy_flow._direct_catalog_match(text)
        if isinstance(direct, dict):
            return direct
    with contextlib.suppress(Exception):
        candidates = list(engine.search_catalog(text, 12) or [])
    if not candidates:
        return None
    for item in candidates:
        for value in _catalog_values(item):
            alias = _normalise(value)
            if alias and (alias in normalized or normalized in alias):
                return item
    return candidates[0] if len(candidates) == 1 else None


def _catalog_by_id_or_name(target_id: str, target_name: str) -> dict[str, Any] | None:
    query = target_name or target_id
    with contextlib.suppress(Exception):
        candidates = list(engine.search_catalog(query, 20) or [])
        for item in candidates:
            if target_id and str(item.get("id") or "") == target_id:
                return item
            if target_name and _normalise(item.get("display_name")) == _normalise(target_name):
                return item
        if len(candidates) == 1:
            return candidates[0]
    return None


def _extract_scene(text: str, item: dict[str, Any] | None = None) -> str:
    result = _normalise(text)
    for phrase in _SELFIE_WORDS:
        result = result.replace(_normalise(phrase), " ")
    if item:
        for value in sorted(_catalog_values(item), key=len, reverse=True):
            alias = _normalise(value)
            if alias:
                result = result.replace(alias, " ")
    result = re.sub(r"\s+", " ", result).strip(" ,.;:-")
    words = result.split()
    while words and words[0] in _SCENE_ONLY_WORDS:
        words.pop(0)
    return " ".join(words).strip()


class _MessageProxy:
    def __init__(self, original: Any, text: str):
        self._original = original
        self.text = text

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


class _UpdateProxy:
    def __init__(self, original: Any, text: str):
        self._original = original
        self.effective_message = _MessageProxy(original.effective_message, text)
        self.effective_user = original.effective_user
        self.effective_chat = original.effective_chat
        self.callback_query = getattr(original, "callback_query", None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


async def _reply_target_required(update: Any, context: Any, scene: str = "") -> None:
    session = _session(context)
    if isinstance(session, dict) and scene:
        session["pending_scene"] = scene
    suffix = f"\nСцена сохранена: «{scene}»." if scene else ""
    await update.effective_message.reply_text(
        "⭐ Сначала выберите, с кем сделать AI-селфи. Без выбранного человека или "
        "загруженных референсов генерация не запускается." + suffix,
        reply_markup=engine._main_menu_kb(),
    )


async def _submit_scene(update: Any, context: Any, scene: str) -> None:
    session = _session(context)
    if not _target_ready(session):
        await _reply_target_required(update, context, scene)
        return
    scene = str(scene or "").strip()
    if not scene:
        await update.effective_message.reply_text(
            "Теперь выберите или опишите сцену.", reply_markup=engine._scene_kb()
        )
        return
    if isinstance(session, dict):
        session["pending_scene"] = scene
        session["state"] = "await_scene"
    proxy = _UpdateProxy(update, scene)
    await engine._on_text(proxy, context)
    if isinstance(session, dict):
        session.pop("pending_scene", None)


async def _prepare_target_and_scene(
    update: Any,
    context: Any,
    item: dict[str, Any],
    scene: str = "",
) -> None:
    session = _session(context)
    if isinstance(session, dict):
        session["pending_target_id"] = str(item.get("id") or "")
        session["pending_target_name"] = str(item.get("display_name") or "")
        if scene:
            session["pending_scene"] = scene
    await engine._prepare_library_refs(update, context, item)
    session = _session(context)
    if scene and _target_ready(session):
        await _submit_scene(update, context, scene)


async def _resume_pending_after_photo(update: Any, context: Any) -> None:
    session = _session(context)
    if not isinstance(session, dict):
        return
    target_id = str(session.pop("pending_target_id", "") or "")
    target_name = str(session.pop("pending_target_name", "") or "")
    scene = str(session.get("pending_scene") or "").strip()
    if target_id or target_name:
        item = _catalog_by_id_or_name(target_id, target_name)
        if item:
            await _prepare_target_and_scene(update, context, item, scene)
            return
    # No target was supplied before the photo: the catalog menu is the next
    # mandatory step, never the generic photo-action menu.
    session["state"] = "choose_celebrity"


async def _entry_callback(update: Any, context: Any) -> None:
    q = update.callback_query
    data = str(getattr(q, "data", "") or "")
    if not (
        data.startswith("act:fun:aiselfie")
        or data == "pedit:aiselfie"
        or data.startswith("celeb:")
    ):
        return
    with contextlib.suppress(Exception):
        await q.answer()

    if data.startswith("act:fun:aiselfie") or data == "pedit:aiselfie":
        if data.endswith("_upload"):
            session = wizard._start_session(context)
            session["state"] = "await_user_photo"
            await wizard._reply(
                update,
                "📤 Пришлите своё селфи. После загрузки автоматически откроется каталог знаменитостей и персонажей.",
                engine._kb([[('❌ Отмена', 'celeb:cancel')]]),
            )
        elif data.endswith("_last"):
            wizard._start_session(context)
            raw = wizard._cached_photo(update)
            if raw:
                await wizard._accept_user_photo(update, context, raw)
                await _resume_pending_after_photo(update, context)
            else:
                session = _session(context)
                if isinstance(session, dict):
                    session["state"] = "await_user_photo"
                await wizard._reply(update, "Последнее фото не найдено. Пришлите новое селфи.")
        else:
            await wizard._open_entry(update, context)
        _stop()

    if data == "celeb:cancel":
        wizard._clear_feature_session(context)
        legacy_flow._clear_legacy_flows(context)
        await update.effective_message.reply_text("❌ Режим AI-селфи отменён.")
        _stop()

    if not _active(context):
        await update.effective_message.reply_text(
            "Эта сессия завершена. Откройте AI-селфи заново.",
            reply_markup=engine._kb([[('📸 Открыть AI-селфи', 'act:fun:aiselfie')]]),
        )
        _stop()

    session = _session(context)
    # A scene callback is invalid until a target/reference pack has been fixed.
    if ("scene" in data or data.startswith("celeb:preset:")) and not _target_ready(session):
        await _reply_target_required(update, context)
        _stop()

    try:
        await engine._on_callback(update, context)
    except Exception as exc:
        from telegram.ext import ApplicationHandlerStop
        if not isinstance(exc, ApplicationHandlerStop):
            log.exception("v162 celebrity callback failed data=%s: %s", data, exc)
            await update.effective_message.reply_text(
                "Не удалось выполнить этот шаг. Вернитесь к выбору человека.",
                reply_markup=engine._main_menu_kb(),
            )
            _stop()

    session = _session(context)
    pending_scene = str((session or {}).get("pending_scene") or "").strip()
    state = str((session or {}).get("state") or "")
    if pending_scene and _target_ready(session) and "scene" in state:
        await _submit_scene(update, context, pending_scene)
    _stop()


async def _image(update: Any, context: Any) -> None:
    if not _active(context):
        return
    legacy_flow._clear_legacy_flows(context)
    session = _session(context)
    state = str((session or {}).get("state") or "")
    raw = await wizard._download_telegram_image(update, context)
    if not raw:
        await update.effective_message.reply_text(
            "Не удалось прочитать изображение. Отправьте JPG/PNG/WEBP как фото Telegram или файл."
        )
        _stop()
    if state == "await_custom_refs":
        await wizard._delegate_custom_reference(update, context, raw)
        _stop()
    if state in {"queued", "generating"}:
        await update.effective_message.reply_text("⏳ Генерация уже выполняется. Дождитесь результата.")
        _stop()
    if state in {"await_user_photo", "choose_user_photo", ""}:
        await wizard._accept_user_photo(update, context, raw)
        await _resume_pending_after_photo(update, context)
        _stop()
    await update.effective_message.reply_text(
        "Селфи пользователя уже сохранено. Выберите человека в каталоге; собственные референсы добавляются кнопкой «Нет в базе».",
        reply_markup=engine._main_menu_kb(),
    )
    _stop()


async def _text(update: Any, context: Any) -> None:
    text = str(getattr(update.effective_message, "text", "") or "").strip()
    normalized = _normalise(text)
    direct = _catalog_match(text) if ("селфи" in normalized or "selfie" in normalized) else None

    if not _active(context):
        if direct is None:
            return
        session = wizard._start_session(context)
        scene = _extract_scene(text, direct)
        session["pending_target_id"] = str(direct.get("id") or "")
        session["pending_target_name"] = str(direct.get("display_name") or "")
        if scene:
            session["pending_scene"] = scene
        cached = wizard._cached_photo(update)
        if not cached:
            session["state"] = "await_user_photo"
            await update.effective_message.reply_text(
                f"⭐ Нашёл: {direct.get('display_name')}. Теперь пришлите своё селфи; затем подтяну референсы и сцену автоматически."
            )
            _stop()
        await wizard._accept_user_photo(update, context, cached)
        await _resume_pending_after_photo(update, context)
        _stop()

    legacy_flow._clear_legacy_flows(context)
    session = _session(context)
    state = str((session or {}).get("state") or "")
    if state in {"await_user_photo", "choose_user_photo"}:
        await update.effective_message.reply_text(
            "Сначала пришлите своё селфи или нажмите «Использовать последнее фото»."
        )
        _stop()

    if state == "choose_celebrity":
        item = _catalog_match(text)
        if item:
            scene = _extract_scene(text, item)
            await _prepare_target_and_scene(update, context, item, scene)
        else:
            scene = _extract_scene(text)
            results = list(engine.search_catalog(text, 8) or [])
            if results:
                await update.effective_message.reply_text(
                    "Нашёл несколько вариантов. Выберите нужного человека:",
                    reply_markup=engine._search_results_kb(results),
                )
                if isinstance(session, dict) and scene:
                    session["pending_scene"] = scene
            else:
                await _reply_target_required(update, context, scene)
        _stop()

    if not _target_ready(session):
        scene = _extract_scene(text)
        await _reply_target_required(update, context, scene)
        _stop()

    # Once a target is fixed, all text is a scene/refinement request handled by
    # the authoritative catalog engine, never by legacy Nano Banana free prompt.
    await engine._on_text(update, context)
    _stop()


def _is_version_handler(handler: Any) -> bool:
    commands = getattr(handler, "commands", None)
    if commands is None:
        return False
    try:
        return "version" in {str(item).casefold() for item in commands}
    except Exception:
        return False


def _remove_duplicate_version_handlers(app: Any) -> None:
    for group, handlers in list(getattr(app, "handlers", {}).items()):
        for handler in list(handlers):
            if _is_version_handler(handler):
                with contextlib.suppress(Exception):
                    app.remove_handler(handler, group=group)


async def _cmd_version(update: Any, context: Any) -> None:
    previous.install_early()
    previous._patch_pipeline()
    mod = previous.previous._runtime_module()
    if mod is not None:
        previous._patch_runtime(mod)
        for attr in ("APP_VERSION", "RELEASE_VERSION", "PRODUCTION_HARDENING_VERSION", "PATCH_VERSION"):
            setattr(mod, attr, VERSION)

    refs: list[str] = []
    ref_error = ""
    try:
        refs = previous._full_reference_paths()
    except Exception as exc:
        ref_error = f"{type(exc).__name__}: {exc}"
    dimensions = previous._reference_dimensions() if refs else []
    packs = previous.previous.previous._packages(mod) if mod is not None else previous.previous.previous._DEFAULT_PACKAGES
    methods = sorted((getattr(mod, "YOO_DIRECT_METHODS", {}) or {}).keys()) if mod is not None else []
    medical_text = bool(mod and getattr(getattr(mod, "_medical_analyze_text", None), "_prod_v120_medical", False))
    medical_image = bool(mod and getattr(getattr(mod, "_medical_analyze_image", None), "_prod_v120_medical", False))
    lines = [
        f"✅ Код запущен: {VERSION}",
        "entrypoint=main.py",
        "start_command=python -u main.py",
        "release_overlay=v162",
        "celebrity_selfie_flow=v162-authoritative-menu+free-text",
        "celebrity_selfie_photo_router=v162-before-all-generic-photo-handlers",
        "celebrity_target_gate=required-before-scene-render",
        "catalog_reference_policy=automatic-3-or-4-reference-pack",
        "custom_character_policy=upload-1-to-4-references",
        "roman_render=v161-hybrid-identity",
        f"fixed_roman_reference_count={len(refs)}",
        f"fixed_roman_reference_dimensions={','.join(dimensions) or '-'}",
        f"fixed_roman_reference_pack={'ready' if len(refs) == 3 else 'warning'}",
        f"fixed_roman_reference_error={ref_error or '-'}",
        "generic_nano_banana_without_target=blocked",
        "version_duplicate_error=blocked",
        f"credit_catalog={','.join(f'{c}:{r}' for c, r in sorted(packs.items()))}",
        f"credit_yookassa_methods={','.join(methods)}",
        f"medical_text_route={'v120' if medical_text else 'legacy'}",
        f"medical_image_route={'v120' if medical_image else 'legacy'}",
        f"medical_card={getattr(mod, 'MEDICAL_CARD_VERSION', '—') if mod is not None else '—'}",
        f"medical_answer_ui={getattr(mod, 'MEDICAL_ANSWER_UI_VERSION', '—') if mod is not None else '—'}",
    ]
    # Deliberately return normally: all older /version handlers were removed from
    # this Application, so ApplicationHandlerStop cannot be misreported by a
    # legacy generic error handler as «Упс, произошла ошибка».
    await update.effective_message.reply_text("\n".join(lines)[:3900])


def _patch_version_contract() -> None:
    with contextlib.suppress(Exception):
        import neyrobot_prod
        from neyrobot_prod import bootstrap, versioning
        neyrobot_prod.VERSION = VERSION
        bootstrap.VERSION = VERSION
        versioning.VERSION = VERSION
    previous.VERSION = VERSION
    previous._cmd_version = _cmd_version


def _patch_runtime(mod: Any) -> bool:
    try:
        previous._patch_runtime(mod)
        for attr in ("APP_VERSION", "RELEASE_VERSION", "PRODUCTION_HARDENING_VERSION", "PATCH_VERSION"):
            setattr(mod, attr, VERSION)
        mod.CELEBRITY_SELFIE_FLOW_VERSION = VERSION
        mod._V162_UNIFIED_SELFIE_FLOW_ACTIVE = True
        return True
    except Exception as exc:
        log.exception("v162 runtime patch failed: %r", exc)
        return False


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return

    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        _remove_duplicate_version_handlers(app)
        if not getattr(app, _HANDLER_FLAG, False):
            app.add_handler(CommandHandler("version", _cmd_version), group=_GROUP)
            app.add_handler(
                CallbackQueryHandler(
                    _entry_callback,
                    pattern=r"^(?:act:fun:aiselfie(?:_.*)?|pedit:aiselfie|celeb:).*$",
                ),
                group=_GROUP,
            )
            app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, _image), group=_GROUP)
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text), group=_GROUP)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


def _start_worker() -> None:
    global _WORKER_STARTED
    if _WORKER_STARTED:
        return
    _WORKER_STARTED = True

    def worker() -> None:
        stable = 0
        for _ in range(3600):
            _patch_version_contract()
            previous._patch_pipeline()
            mod = previous.previous._runtime_module()
            runtime_ok = bool(mod is not None and _patch_runtime(mod))
            stable = stable + 1 if runtime_ok else 0
            if stable >= 120:
                return
            time.sleep(0.1)

    threading.Thread(target=worker, name="neyrobot-hotfix-v162", daemon=True).start()


def install_early() -> None:
    with _LOCK:
        previous.install_early()
        wizard.install_builder_hook()
        install_builder_hook()
        _patch_version_contract()
        _start_worker()


__all__ = [
    "VERSION", "install_early", "install_builder_hook", "_entry_callback", "_image", "_text",
    "_catalog_match", "_extract_scene", "_target_ready", "_submit_scene", "_cmd_version",
]
