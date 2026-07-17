# -*- coding: utf-8 -*-
"""Presentation Studio v107 runtime patch.

Keeps final visual/style/palette additions inside their current wizard context.
A note entered from the final review is confirmed explicitly and then returns
straight to the PDF/PPTX build screen. It must never be routed into the
multipart main-brief collector or restart structure/logo steps.
"""
from __future__ import annotations

import contextlib
import sys
import threading
import time
from typing import Any

VERSION = "v107-presentation-final-note-return-2026-07-17"

_AWAIT_STAGE = {
    "visual_note": "v107_await_visual_note",
    "style_note": "v107_await_style_note",
    "palette_note": "v107_await_palette_note",
}
_NOTE_KEY = {
    "visual_note": "visual_notes",
    "style_note": "style_notes",
    "palette_note": "palette_notes",
}
_NOTE_LABEL = {
    "visual_note": "визуальному брифу",
    "style_note": "стилю",
    "palette_note": "палитре",
}
_STAGE_TO_KIND = {stage: kind for kind, stage in _AWAIT_STAGE.items()}
_CONFIRM_STAGE = "v107_note_confirmation"


def _confirmation_kb(mod):
    return mod._kb([
        [("✅ Бриф дополнен — вернуться к сборке", "ps:v107_note_confirm")],
        [("✏️ Добавить ещё одно уточнение", "ps:v107_note_more")],
        [("🗑 Отменить последнее дополнение", "ps:v107_note_cancel")],
        [("❌ Отменить проект", "ps:cancel")],
    ])


def _clear_brief_routing(project: dict[str, Any]) -> None:
    """Disable every known main-brief collector flag for note-entry stages."""
    project["brief_v106_active"] = False
    project.pop("brief_v106_pending_replace", None)
    project.pop("brief_auto_finalize_at", None)
    project.pop("brief_collect_deadline", None)
    project.pop("brief_timer_token", None)


def _return_markup(mod, return_stage: str):
    return mod.FINAL_KB if return_stage == "final_review" else mod.ENGINE_KB


def _return_text(mod, project: dict[str, Any], prefix: str) -> str:
    return_stage = str(project.get("v107_note_return_stage") or "final_review")
    if return_stage == "final_review":
        return prefix + "\n\n" + mod._review_text(project)
    return prefix + "\n\nВозвращаюсь к выбору движка изображений."


def _remove_pending_note(project: dict[str, Any]) -> bool:
    pending = project.get("v107_pending_note") or {}
    key = str(pending.get("key") or "")
    value = str(pending.get("value") or "")
    try:
        index = int(pending.get("index"))
    except Exception:
        index = -1
    notes = project.get(key)
    if not key or not isinstance(notes, list):
        return False
    if 0 <= index < len(notes) and str(notes[index]) == value:
        notes.pop(index)
        return True
    for pos in range(len(notes) - 1, -1, -1):
        if str(notes[pos]) == value:
            notes.pop(pos)
            return True
    return False


def patch_module(mod) -> None:
    if getattr(mod, "_V107_FINAL_NOTE_PATCHED", False):
        return

    original_handle_text = mod.PresentationStudio.handle_text
    original_handle_callback = mod.PresentationStudio.handle_callback

    async def handle_text(self, update, context, text: str) -> bool:
        if not update.effective_user or not update.effective_chat:
            return False
        project = self._active_project(update.effective_user.id, update.effective_chat.id)
        if not project:
            return False
        stage = str(project.get("stage") or "")
        kind = _STAGE_TO_KIND.get(stage)
        if not kind:
            return await original_handle_text(self, update, context, text)

        clean = str(text or "").strip()
        if not clean:
            await mod._reply(update, "Уточнение пустое. Пришлите текст дополнения.")
            return True

        key = _NOTE_KEY[kind]
        notes = project.setdefault(key, [])
        notes.append(clean)
        project["v107_pending_note"] = {
            "kind": kind,
            "key": key,
            "value": clean,
            "index": len(notes) - 1,
        }
        project["stage"] = _CONFIRM_STAGE
        _clear_brief_routing(project)
        if kind == "palette_note":
            with contextlib.suppress(Exception):
                project["palette"] = mod._parse_palette(project)
        if kind == "visual_note":
            project.pop("visual_prompt_hash", None)
            project.pop("slide_prompt_hashes", None)
            project.pop("image_prompt_hashes", None)
        mod._save(project["user_id"], project)
        context.user_data["presentation_studio_active"] = project.get("project_id")
        await mod._reply(
            update,
            f"✅ Дополнение к {_NOTE_LABEL[kind]} сохранено.\n\n"
            "Подтвердите, что уточнение закончено, либо добавьте ещё одно. "
            "Структура, логотип, стиль, палитра и выбранный движок не изменяются.",
            _confirmation_kb(mod),
        )
        return True

    async def handle_callback(self, update, context) -> bool:
        q = update.callback_query
        data = (q.data or "") if q else ""
        project = mod._load(q.from_user.id) if q else None

        if project and data in {"ps:visual_note", "ps:style_note", "ps:palette_note"} and str(project.get("stage") or "") in {"engine_choice", "final_review"}:
            with contextlib.suppress(Exception):
                await q.answer()
            kind = data[len("ps:"):]
            return_stage = str(project.get("stage") or "final_review")
            project["v107_note_return_stage"] = return_stage
            project["note_return_stage"] = return_stage
            project["v107_note_kind"] = kind
            project["stage"] = _AWAIT_STAGE[kind]
            _clear_brief_routing(project)
            mod._save(project["user_id"], project)
            prompt = {
                "visual_note": "Введите дополнение к визуальному брифу. После сохранения я попрошу подтвердить завершение и верну вас к финальной сборке.",
                "style_note": "Введите дополнение к стилю. После сохранения я попрошу подтвердить завершение и верну вас к финальной сборке.",
                "palette_note": "Введите дополнение к палитре. После сохранения я попрошу подтвердить завершение и верну вас к финальной сборке.",
            }[kind]
            await mod._reply(update, prompt)
            return True

        if project and data.startswith("ps:v107_note_"):
            with contextlib.suppress(Exception):
                await q.answer()
            action = data[len("ps:"):]
            pending = project.get("v107_pending_note") or {}
            kind = str(pending.get("kind") or project.get("v107_note_kind") or "visual_note")
            return_stage = str(project.get("v107_note_return_stage") or "final_review")

            if action == "v107_note_more":
                project.pop("v107_pending_note", None)
                project["stage"] = _AWAIT_STAGE.get(kind, _AWAIT_STAGE["visual_note"])
                _clear_brief_routing(project)
                mod._save(project["user_id"], project)
                await mod._reply(update, "Введите следующее уточнение. Все предыдущие дополнения сохранены.")
                return True

            if action == "v107_note_cancel":
                removed = _remove_pending_note(project)
                project.pop("v107_pending_note", None)
                project.pop("v107_note_kind", None)
                project.pop("note_return_stage", None)
                project["stage"] = return_stage
                _clear_brief_routing(project)
                if kind == "palette_note":
                    with contextlib.suppress(Exception):
                        project["palette"] = mod._parse_palette(project)
                mod._save(project["user_id"], project)
                prefix = "Последнее дополнение отменено." if removed else "Дополнение уже отсутствует."
                await mod._reply(update, _return_text(mod, project, prefix), _return_markup(mod, return_stage))
                return True

            if action == "v107_note_confirm":
                project.pop("v107_pending_note", None)
                project.pop("v107_note_kind", None)
                project.pop("note_return_stage", None)
                project["stage"] = return_stage
                _clear_brief_routing(project)
                mod._save(project["user_id"], project)
                await mod._reply(
                    update,
                    _return_text(mod, project, "✅ Дополнение подтверждено. Возвращаюсь к финальному этапу."),
                    _return_markup(mod, return_stage),
                )
                return True

        if project and data == "ps:resume" and str(project.get("note_return_stage") or "") == "final_review":
            with contextlib.suppress(Exception):
                await q.answer()
            project["stage"] = "final_review"
            project.pop("note_return_stage", None)
            project.pop("v107_pending_note", None)
            _clear_brief_routing(project)
            mod._save(project["user_id"], project)
            await mod._reply(
                update,
                "✅ Восстановил финальный этап после дополнения визуального брифа.\n\n" + mod._review_text(project),
                mod.FINAL_KB,
            )
            return True

        return await original_handle_callback(self, update, context)

    mod.PresentationStudio.handle_text = handle_text
    mod.PresentationStudio.handle_callback = handle_callback
    mod._V107_FINAL_NOTE_PATCHED = True
    mod.PRESENTATION_PATCH_VERSION = VERSION


def patch_main_version_async() -> None:
    def worker() -> None:
        for _ in range(600):
            for name in ("__main__", "main"):
                module = sys.modules.get(name)
                if module is not None:
                    with contextlib.suppress(Exception):
                        setattr(module, "PATCH_VERSION", VERSION)
            time.sleep(0.1)

    threading.Thread(target=worker, name="presentation-v107-version", daemon=True).start()


__all__ = ["VERSION", "patch_module", "patch_main_version_async"]
