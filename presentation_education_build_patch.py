# -*- coding: utf-8 -*-
"""Allow non-commercial educational decks to render without invented contacts.

Commercial decks keep the existing strict validation and contact requirements.
This patch only owns the final build callback for a brief that contains no
commercial intent and no real contact data.
"""
from __future__ import annotations

import contextlib
from typing import Any

VERSION = "v119-educational-build-gate-2026-11-11"
_FLAG = "_V119_EDUCATIONAL_BUILD_PATCHED"

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
    if contacts or prices:
        return False
    return not any(token in raw for token in _COMMERCIAL_RE)


async def _send_ready_documents(mod: Any, update: Any, pdf_path: str, pptx_path: str) -> tuple[str, str]:
    send = getattr(mod, "_v101_send_document", None)
    if callable(send):
        pdf_status = await send(update, pdf_path, "Готовый PDF")
        pptx_status = await send(update, pptx_path, "Редактируемый PPTX")
        return str(pdf_status), str(pptx_status)

    results = []
    for path, caption in ((pdf_path, "Готовый PDF"), (pptx_path, "Редактируемый PPTX")):
        try:
            with open(path, "rb") as fh:
                await update.effective_message.reply_document(
                    mod.InputFile(fh, filename=mod.Path(path).name), caption=caption
                )
            results.append("ok")
        except Exception:
            results.append("failed")
    return tuple(results)


def patch_module(mod: Any) -> bool:
    if getattr(mod, _FLAG, False):
        return True
    previous_callback = mod.on_callback

    async def on_callback(update: Any, context: Any) -> None:
        q = getattr(update, "callback_query", None)
        data = str(getattr(q, "data", "") or "")
        if data != "ps:build":
            return await previous_callback(update, context)

        project = mod._load(q.from_user.id) if q else None
        if not project or not _is_educational_project(project):
            return await previous_callback(update, context)

        with contextlib.suppress(Exception):
            await q.answer()
        project["stage"] = "building"
        project["last_build_step"] = "starting"
        project["last_build_errors"] = []
        mod._save(project["user_id"], project)
        await mod._reply(
            update,
            "Начинаю сборку учебной презентации. Контакты не требуются: их нет в исходном брифе.",
        )
        with contextlib.suppress(Exception):
            await context.bot.send_chat_action(
                update.effective_chat.id, mod.ChatAction.UPLOAD_DOCUMENT
            )

        async def render_action():
            return await mod._build_files(project, update, context)

        try:
            runner = getattr(mod, "_STUDIO_PAID_RUNNER", None)
            if runner is not None:
                built = await runner(
                    update,
                    context,
                    "img",
                    "presentation_render",
                    float(getattr(mod, "_STUDIO_RENDER_COST_USD", 0.0) or 0.0),
                    render_action,
                )
            else:
                built = await render_action()
        except Exception as exc:
            fresh = mod._load(project["user_id"]) or project
            fresh["stage"] = "final_review"
            compact = getattr(mod, "_v101_compact_error", lambda value: str(value)[:260])
            fresh.setdefault("last_build_errors", []).append(compact(exc))
            mod._save(fresh["user_id"], fresh)
            await mod._reply(
                update,
                "Не удалось собрать файлы. Проект сохранён; повторная генерация брифа не требуется.\n"
                f"Этап: {fresh.get('last_build_step', 'не определён')}\n"
                + "\n".join(f"• {item}" for item in fresh["last_build_errors"][-4:]),
                mod.FINAL_KB,
            )
            raise mod.ApplicationHandlerStop

        if not built:
            fresh = mod._load(project["user_id"]) or project
            fresh["stage"] = "final_review"
            mod._save(fresh["user_id"], fresh)
            await mod._reply(
                update,
                "Сборка не завершена. Проект сохранён; нажмите «Собрать PDF + PPTX» ещё раз.",
                mod.FINAL_KB,
            )
            raise mod.ApplicationHandlerStop

        pdf_path, pptx_path = built
        pdf_status, pptx_status = await _send_ready_documents(mod, update, pdf_path, pptx_path)
        fresh = mod._load(project["user_id"]) or project
        failures = {"failed", "missing"}
        if pdf_status in failures or pptx_status in failures:
            fresh["stage"] = "final_review"
            mod._save(fresh["user_id"], fresh)
            keyboard = mod.FINAL_KB
            tail = "\nОдин формат не отправился. Готовый файл сохранён; можно повторить отправку."
        else:
            keyboard = mod._kb([
                [("📄 Скачать PDF ещё раз", "ps:download_pdf"), ("📊 Скачать PPTX ещё раз", "ps:download_pptx")],
                [("🆕 Новый проект", "ps:new")],
            ])
            tail = ""
        await mod._reply(
            update,
            f"Сборка завершена.\nPDF: {pdf_status}\nPPTX: {pptx_status}{tail}",
            keyboard,
        )
        raise mod.ApplicationHandlerStop

    mod.on_callback = on_callback
    mod.PRESENTATION_EDUCATIONAL_BUILD_PATCH_VERSION = VERSION
    setattr(mod, _FLAG, True)
    return True


__all__ = ["VERSION", "patch_module"]
