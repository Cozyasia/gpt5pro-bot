# -*- coding: utf-8 -*-
"""Allow non-commercial educational decks to render without invented contacts.

Commercial decks keep the strict preflight.  Educational decks may not have a
CTA or contacts, but still use the normal paid image pipeline.  The visual
phase deliberately runs before the final render charge: nesting both inside
the same per-user generation lock would otherwise deadlock.
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Any

VERSION = "v120-educational-build-lock-safe-2026-11-11"
_FLAG = "_V120_EDUCATIONAL_BUILD_PATCHED"

_COMMERCIAL_RE = (
    "продаж", "реклам", "коммерческ", "бренд", "компани", "клиент",
    "продукт", "товар", "услуг", "прайс", "тариф", "цен", "стоимост",
    "заказ", "покупател", "контакт", "телеграм", "сайт", "email",
    "instagram", "whatsapp", "вебинар", "лид",
)


def _is_educational_project(project: dict[str, Any]) -> bool:
    raw = str(project.get("raw_brief") or "").lower().replace("ё", "е")
    profile = project.get("profile") or {}
    contacts = list(profile.get("contacts") or [])
    prices = list(profile.get("prices") or [])
    return not contacts and not prices and not any(token in raw for token in _COMMERCIAL_RE)


async def _send_ready_documents(mod: Any, update: Any, pdf_path: str, pptx_path: str) -> tuple[str, str]:
    send = getattr(mod, "_v101_send_document", None)
    if callable(send):
        return str(await send(update, pdf_path, "Готовый PDF")), str(await send(update, pptx_path, "Редактируемый PPTX"))
    result: list[str] = []
    for path, caption in ((pdf_path, "Готовый PDF"), (pptx_path, "Редактируемый PPTX")):
        try:
            with open(path, "rb") as fh:
                await update.effective_message.reply_document(mod.InputFile(fh, filename=mod.Path(path).name), caption=caption)
            result.append("ok")
        except Exception:
            result.append("failed")
    return tuple(result)  # type: ignore[return-value]


def patch_module(mod: Any) -> bool:
    if getattr(mod, _FLAG, False):
        return True
    previous_callback = mod.on_callback

    async def on_callback(update: Any, context: Any) -> None:
        q = getattr(update, "callback_query", None)
        if str(getattr(q, "data", "") or "") != "ps:build":
            return await previous_callback(update, context)
        project = mod._load(q.from_user.id) if q else None
        if not project or not _is_educational_project(project):
            return await previous_callback(update, context)

        with contextlib.suppress(Exception):
            await q.answer()
        project.update(stage="building", last_build_step="starting", last_build_errors=[])
        mod._save(project["user_id"], project)
        await mod._reply(update, "Начинаю сборку учебной презентации. Контакты не требуются: их нет в исходном брифе.")
        with contextlib.suppress(Exception):
            await context.bot.send_chat_action(update.effective_chat.id, mod.ChatAction.UPLOAD_DOCUMENT)

        try:
            # This part may invoke _presentation_paid_runner for the actual image
            # provider.  Keep it outside the enclosing render runner so the
            # per-user semaphore is never acquired recursively.
            project["last_build_step"] = "deck_content"
            rebuild = getattr(mod, "_v104_repair_slides", None)
            if not callable(rebuild):
                raise RuntimeError("Не найден безопасный сборщик учебных слайдов")
            slides = rebuild(project)
            if not slides:
                raise RuntimeError("Не удалось подготовить учебные слайды")
            project["final_slides"] = slides
            mod._save(project["user_id"], project)

            project["last_build_step"] = "image_generation"
            images = await mod._prepare_slide_images(project, slides, update, context)
            pdir = mod._project_dir(project["user_id"], project["project_id"])
            sanitize = getattr(mod, "_v99_sanitize_images", None)
            if callable(sanitize):
                images = sanitize(images, pdir)
            project["slide_images"] = {str(key): value for key, value in images.items()}
            mod._save(project["user_id"], project)

            async def render_files() -> tuple[str, str]:
                # No provider call happens here, so the render payment lock is
                # safe and correctly scopes only the local file-build stage.
                project["last_build_step"] = "pptx_render"
                brand = mod._safe_filename(project.get("profile", {}).get("brand_name", "presentation"))
                pptx_path = pdir / f"{brand}_presentation.pptx"
                pdf_path = pdir / f"{brand}_presentation.pdf"
                await asyncio.to_thread(mod._build_pptx, project, slides, images, pptx_path)
                project["last_build_step"] = "pdf_render"
                await asyncio.to_thread(mod._build_pdf, project, slides, images, pdf_path)
                project.update(pptx_path=str(pptx_path), pdf_path=str(pdf_path), stage="done", last_build_step="files_ready")
                mod._save(project["user_id"], project)
                return str(pdf_path), str(pptx_path)

            runner = getattr(mod, "_STUDIO_PAID_RUNNER", None)
            built = await runner(update, context, "img", "presentation_render", float(getattr(mod, "_STUDIO_RENDER_COST_USD", 0.0) or 0.0), render_files) if runner else await render_files()
        except Exception as exc:
            fresh = mod._load(project["user_id"]) or project
            fresh["stage"] = "final_review"
            compact = getattr(mod, "_v101_compact_error", lambda value: str(value)[:260])
            fresh.setdefault("last_build_errors", []).append(compact(exc))
            mod._save(fresh["user_id"], fresh)
            await mod._reply(update, "Не удалось собрать файлы. Проект сохранён; повторная генерация брифа не требуется.\n" + f"Этап: {fresh.get('last_build_step', 'не определён')}\n" + "\n".join(f"• {item}" for item in fresh["last_build_errors"][-4:]), mod.FINAL_KB)
            raise mod.ApplicationHandlerStop

        if not built:
            fresh = mod._load(project["user_id"]) or project
            fresh["stage"] = "final_review"
            mod._save(fresh["user_id"], fresh)
            await mod._reply(update, "Сборка не завершена. Проект сохранён; нажмите «Собрать PDF + PPTX» ещё раз.", mod.FINAL_KB)
            raise mod.ApplicationHandlerStop

        pdf_path, pptx_path = built
        pdf_status, pptx_status = await _send_ready_documents(mod, update, pdf_path, pptx_path)
        fresh = mod._load(project["user_id"]) or project
        if pdf_status in {"failed", "missing"} or pptx_status in {"failed", "missing"}:
            fresh["stage"] = "final_review"; mod._save(fresh["user_id"], fresh)
            keyboard, tail = mod.FINAL_KB, "\nОдин формат не отправился. Готовый файл сохранён; можно повторить отправку."
        else:
            keyboard = mod._kb([[("📄 Скачать PDF ещё раз", "ps:download_pdf"), ("📊 Скачать PPTX ещё раз", "ps:download_pptx")], [("🆕 Новый проект", "ps:new")]])
            tail = ""
        await mod._reply(update, f"Сборка завершена.\nPDF: {pdf_status}\nPPTX: {pptx_status}{tail}", keyboard)
        raise mod.ApplicationHandlerStop

    mod.on_callback = on_callback
    mod.PRESENTATION_EDUCATIONAL_BUILD_PATCH_VERSION = VERSION
    setattr(mod, _FLAG, True)
    return True


__all__ = ["VERSION", "patch_module"]
