# -*- coding: utf-8 -*-
"""Presentation Studio v121: permissive brief build and voice brief input.

The previous presentation preflight treated optional commercial sections as
mandatory (service package, two contact channels, three benefits and three
implementation stages). That rejected otherwise usable briefs and made the
wizard impractical for ordinary users.

This overlay keeps only structural blockers, preserves all factual safeguards,
and routes voice/audio messages into the active main-brief collector. The
actual PDF/PPTX render still uses Presentation Studio's normal billing,
providers, state storage and renderers.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any

VERSION = "v121-presentation-relaxed-brief-voice-2026-07-18"

_BUILD_LOCKS: dict[int, asyncio.Lock] = {}
_BRIEF_STAGES = {
    "await_brief",
    "brief_collecting",
    "brief_waiting",
    "brief_parts",
    "await_brief_parts",
    "brief_v106_collecting",
}


def _presentation_module():
    with contextlib.suppress(Exception):
        import presentation_studio as studio
        return studio
    return None


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def assess_project(project: dict[str, Any] | None) -> dict[str, Any]:
    """Return minimal blockers and non-blocking warnings for a deck project."""
    project = project if isinstance(project, dict) else {}
    raw = str(project.get("raw_brief") or "").strip()
    structure = project.get("structure") or []
    profile = project.get("profile") or {}

    blockers: list[str] = []
    warnings: list[str] = []

    if len(raw) < 80:
        blockers.append("главный бриф слишком короткий")
    if not isinstance(structure, list) or len(structure) < 6:
        blockers.append("не сформирована рабочая структура минимум из 6 слайдов")

    # These fields improve a deck but must never block generation.
    contacts = profile.get("contacts") or []
    prices = profile.get("prices") or []
    if not contacts:
        warnings.append("контакты не указаны — финальный слайд будет нейтральным")
    if not prices:
        warnings.append("цены не указаны — бот не будет их выдумывать")
    if not str(profile.get("audience") or "").strip():
        warnings.append("аудитория не выделена отдельно")
    if not str(profile.get("positioning") or "").strip():
        warnings.append("позиционирование не выделено отдельно")

    return {
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "brief_chars": len(raw),
        "slide_count": len(structure) if isinstance(structure, list) else 0,
    }


def _active_project(studio: Any, update: Any) -> dict[str, Any] | None:
    user = getattr(update, "effective_user", None)
    chat = getattr(update, "effective_chat", None)
    if user is None:
        return None
    project = studio._load(int(user.id))
    if not isinstance(project, dict):
        return None
    project_chat = int(project.get("chat_id") or 0)
    current_chat = int(getattr(chat, "id", 0) or 0)
    if project_chat not in (0, current_chat):
        return None
    return project


async def _send_existing_files(studio: Any, update: Any, project: dict[str, Any]) -> bool:
    from telegram import InputFile

    pdf_path = str(project.get("pdf_path") or "")
    pptx_path = str(project.get("pptx_path") or "")
    if not (pdf_path and pptx_path and os.path.exists(pdf_path) and os.path.exists(pptx_path)):
        return False
    with open(pdf_path, "rb") as fh:
        await update.effective_message.reply_document(
            InputFile(fh, filename=Path(pdf_path).name), caption="Готовый PDF"
        )
    with open(pptx_path, "rb") as fh:
        await update.effective_message.reply_document(
            InputFile(fh, filename=Path(pptx_path).name), caption="Редактируемый PPTX"
        )
    return True


async def _build_files_without_optional_preflight(
    studio: Any,
    project: dict[str, Any],
    update: Any,
    context: Any,
) -> tuple[str, str]:
    """Run the canonical render pipeline without optional-field completeness gates."""
    project["palette"] = studio._parse_palette(project)
    slides = await studio._generate_deck_content(project, update)
    if not isinstance(slides, list) or not slides:
        slides = []
        for item in project.get("structure") or []:
            if not isinstance(item, dict):
                continue
            slides.append({
                **item,
                "subtitle": str(item.get("subtitle") or ""),
                "bullets": list(item.get("bullets") or [])[:6],
                "image_prompt": str(item.get("image_prompt") or ""),
            })
    if len(slides) < 6:
        raise RuntimeError("Presentation structure is incomplete")

    studio._save(project["user_id"], project)
    images = await studio._prepare_slide_images(project, slides, update, context)
    studio._save(project["user_id"], project)

    project_dir = studio._project_dir(project["user_id"], project["project_id"])
    brand = studio._safe_filename(
        project.get("profile", {}).get("brand_name", "presentation")
    )
    pptx_path = project_dir / f"{brand}_presentation.pptx"
    pdf_path = project_dir / f"{brand}_presentation.pdf"

    await asyncio.to_thread(studio._build_pptx, project, slides, images, pptx_path)
    await asyncio.to_thread(studio._build_pdf, project, slides, images, pdf_path)

    project["final_slides"] = slides
    project["pptx_path"] = str(pptx_path)
    project["pdf_path"] = str(pdf_path)
    project["stage"] = "done"
    project["build_finished_at"] = int(time.time())
    studio._save(project["user_id"], project)
    return str(pdf_path), str(pptx_path)


async def _build_callback(update: Any, context: Any) -> None:
    from telegram import InputFile
    from telegram.constants import ChatAction
    from telegram.ext import ApplicationHandlerStop

    query = getattr(update, "callback_query", None)
    if query is None or str(query.data or "") != "ps:build":
        return
    with contextlib.suppress(Exception):
        await query.answer()

    studio = _presentation_module()
    if studio is None:
        await update.effective_message.reply_text(
            "Модуль презентаций ещё загружается. Повторите действие через несколько секунд."
        )
        raise ApplicationHandlerStop

    project = _active_project(studio, update)
    if not project:
        await studio._reply(update, "Проект не найден. Создайте новый проект.", studio.START_KB)
        raise ApplicationHandlerStop

    user_id = int(project.get("user_id") or getattr(update.effective_user, "id", 0) or 0)
    lock = _BUILD_LOCKS.setdefault(user_id, asyncio.Lock())
    if lock.locked():
        await studio._reply(update, "Сборка уже выполняется. Дождитесь PDF и PPTX.")
        raise ApplicationHandlerStop

    async with lock:
        project = _active_project(studio, update) or project
        if project.get("stage") == "done" and await _send_existing_files(studio, update, project):
            await studio._reply(update, "Файлы уже были собраны — отправил их повторно без нового списания.")
            raise ApplicationHandlerStop

        assessment = assess_project(project)
        if not assessment["ready"]:
            await studio._reply(
                update,
                "Пока нельзя собрать презентацию:\n• "
                + "\n• ".join(assessment["blockers"])
                + "\n\nВернитесь к структуре или дополните описание проекта.",
                studio.FINAL_KB,
            )
            raise ApplicationHandlerStop

        project["stage"] = "building"
        project["build_started_at"] = int(time.time())
        studio._save(user_id, project)

        warning_text = ""
        if assessment["warnings"]:
            warning_text = (
                "\n\nНекоторые необязательные данные не указаны. Это не блокирует сборку: "
                "бот использует только факты из брифа и ничего не выдумывает."
            )
        await studio._reply(
            update,
            "Начинаю сборку PDF + PPTX. Главный бриф и утверждённая структура достаточны. "
            "Отсутствие второго контакта, отдельного сервисного пакета, списка преимуществ "
            "или формальных этапов больше не останавливает генерацию."
            + warning_text,
        )
        with contextlib.suppress(Exception):
            await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_DOCUMENT)

        async def render_action():
            return await _build_files_without_optional_preflight(studio, project, update, context)

        try:
            paid_runner = getattr(studio, "_STUDIO_PAID_RUNNER", None)
            if paid_runner is not None:
                built = await paid_runner(
                    update,
                    context,
                    "img",
                    "presentation_render",
                    float(getattr(studio, "_STUDIO_RENDER_COST_USD", 0.0) or 0.0),
                    render_action,
                )
            else:
                built = await render_action()

            if not built:
                project["stage"] = "final_review"
                studio._save(user_id, project)
                raise ApplicationHandlerStop

            pdf_path, pptx_path = built
            with open(pdf_path, "rb") as fh:
                await update.effective_message.reply_document(
                    InputFile(fh, filename=Path(pdf_path).name), caption="Готовый PDF"
                )
            with open(pptx_path, "rb") as fh:
                await update.effective_message.reply_document(
                    InputFile(fh, filename=Path(pptx_path).name), caption="Редактируемый PPTX"
                )
            await studio._reply(
                update,
                "Проект собран. Главный бриф и все дополнения сохранены.",
                studio._kb([
                    [("📄 Скачать PDF ещё раз", "ps:download_pdf"), ("📊 Скачать PPTX ещё раз", "ps:download_pptx")],
                    [("🆕 Новый проект", "ps:new")],
                ]),
            )
        except ApplicationHandlerStop:
            raise
        except Exception as exc:
            project["stage"] = "final_review"
            project["build_error_at"] = int(time.time())
            studio._save(user_id, project)
            await studio._local_error(update, "v121_relaxed_build", exc)

    raise ApplicationHandlerStop


async def _transcribe_active_brief(update: Any, context: Any) -> None:
    from telegram.constants import ChatAction
    from telegram.ext import ApplicationHandlerStop

    studio = _presentation_module()
    if studio is None:
        return
    project = _active_project(studio, update)
    if not project:
        return

    stage = str(project.get("stage") or "")
    if stage not in _BRIEF_STAGES and not bool(project.get("brief_v106_active")):
        return

    message = getattr(update, "effective_message", None)
    media = getattr(message, "voice", None) or getattr(message, "audio", None)
    if message is None or media is None:
        return

    with contextlib.suppress(Exception):
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    await message.reply_text("🎙 Распознаю голосовой бриф и добавляю его в проект…")

    try:
        tg_file = await media.get_file()
        raw = bytes(await tg_file.download_as_bytearray())
        filename = str(getattr(media, "file_name", "") or "voice.ogg")
        runtime = _runtime_module()
        transcript = ""

        stt_bytes = getattr(runtime, "_stt_transcribe_bytes", None) if runtime is not None else None
        if callable(stt_bytes):
            transcript = str(await stt_bytes(filename, raw) or "").strip()
        else:
            stt_stream = getattr(runtime, "transcribe_audio", None) if runtime is not None else None
            if callable(stt_stream):
                stream = BytesIO(raw)
                stream.name = filename
                transcript = str(await stt_stream(stream, filename) or "").strip()

        if len(transcript) < 30:
            await message.reply_text(
                "Не удалось получить содержательный текст. Запишите голосовое чуть громче или отправьте описание текстом."
            )
            raise ApplicationHandlerStop

        await message.reply_text(
            f"✅ Голос распознан: {len(transcript)} символов. Сохраняю как часть главного брифа."
        )
        try:
            import presentation_v106_patch as multipart
            await multipart._collect_text(studio, update, context, project, transcript)
        except Exception:
            project["stage"] = "await_brief"
            studio._save(project["user_id"], project)
            await studio._process_text_value(update, context, transcript)
    except ApplicationHandlerStop:
        raise
    except Exception as exc:
        await studio._local_error(update, "v121_voice_brief", exc)

    raise ApplicationHandlerStop


def install_builder_hook() -> None:
    """Register build and voice handlers before legacy presentation callbacks."""
    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler, MessageHandler, filters
    except Exception:
        return
    if getattr(ApplicationBuilder, "_presentation_relaxed_v121_hooked", False):
        return

    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, "_presentation_relaxed_v121_handlers", False):
            app.add_handler(
                CallbackQueryHandler(_build_callback, pattern=r"^ps:build$"),
                group=-60,
            )
            app.add_handler(
                MessageHandler(filters.VOICE | filters.AUDIO, _transcribe_active_brief),
                group=-60,
            )
            setattr(app, "_presentation_relaxed_v121_handlers", True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, "_presentation_relaxed_v121_hooked", True)


def install_version_async() -> None:
    def worker() -> None:
        for _ in range(12000):
            mod = _runtime_module()
            if mod is not None:
                with contextlib.suppress(Exception):
                    mod.PRESENTATION_RELAXED_VERSION = VERSION
            time.sleep(0.05)

    threading.Thread(
        target=worker,
        daemon=True,
        name="presentation-relaxed-v121-version",
    ).start()


__all__ = ["VERSION", "assess_project", "install_builder_hook", "install_version_async"]
