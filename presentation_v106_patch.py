# -*- coding: utf-8 -*-
"""Presentation Studio v106 runtime patch.

Fixes the multi-message main-brief workflow introduced in v105:
- no automatic four-second finalization;
- numbered parts are stored and ordered explicitly;
- structure analysis starts only after an explicit confirmation;
- status checks never mutate or finish the brief;
- missing / duplicate / out-of-order parts are handled safely.
"""
from __future__ import annotations

import asyncio
import contextlib
import re
import sys
import threading
import time
from typing import Any

VERSION = "v106-presentation-explicit-multipart-2026-07-17"
COLLECT_STAGE = "brief_v106_collecting"
PROCESS_STAGE = "brief_v106_processing"

_PART_RE = re.compile(
    r"(?:ГЛАВНЫЙ\s+БРИФ\s*[—–-]\s*)?ЧАСТЬ\s*(\d{1,3})\s*(?:ИЗ|/)\s*(\d{1,3})",
    re.IGNORECASE,
)
_BRIEF_STAGES = {
    "await_brief",
    "brief_collecting",
    "brief_waiting",
    "brief_parts",
    "await_brief_parts",
    COLLECT_STAGE,
}


def _clean_part_text(text: str) -> str:
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and _PART_RE.search(lines[0]):
        lines.pop(0)
    return "\n".join(lines).strip()


def _parse_part_marker(text: str) -> tuple[int | None, int | None]:
    match = _PART_RE.search((text or "")[:500])
    if not match:
        return None, None
    number = int(match.group(1))
    total = int(match.group(2))
    if number < 1 or total < 1 or number > total or total > 50:
        return None, None
    return number, total


def _parts(project: dict[str, Any]) -> dict[int, str]:
    raw = project.get("brief_v106_parts") or {}
    result: dict[int, str] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                idx = int(key)
            except Exception:
                continue
            value = str(value or "").strip()
            if idx > 0 and value:
                result[idx] = value
    return result


def _write_parts(project: dict[str, Any], parts: dict[int, str]) -> None:
    project["brief_v106_parts"] = {str(k): v for k, v in sorted(parts.items())}


def _expected(project: dict[str, Any]) -> int:
    try:
        value = int(project.get("brief_v106_expected_parts") or 0)
    except Exception:
        value = 0
    return max(0, min(value, 50))


def _missing(project: dict[str, Any]) -> list[int]:
    expected = _expected(project)
    if not expected:
        return []
    present = set(_parts(project))
    return [idx for idx in range(1, expected + 1) if idx not in present]


def _complete(project: dict[str, Any]) -> bool:
    expected = _expected(project)
    return bool(expected and not _missing(project))


def _combined(project: dict[str, Any]) -> str:
    return "\n\n".join(_parts(project)[idx] for idx in sorted(_parts(project))).strip()


def _brief_kb(mod, project: dict[str, Any]):
    if _complete(project):
        primary = ("✅ Подтвердить и распознать бриф", "ps:v106_brief_finish")
    else:
        primary = ("✅ Завершить досрочно", "ps:v106_brief_finish_early")
    return mod._kb([
        [primary],
        [("📊 Проверить полученные части", "ps:v106_brief_status")],
        [("🧹 Очистить и ввести заново", "ps:v106_brief_clear")],
        [("❌ Отменить проект", "ps:cancel")],
    ])


def _confirm_early_kb(mod):
    return mod._kb([
        [("⚠️ Да, завершить неполный бриф", "ps:v106_brief_finish_early_confirm")],
        [("↩️ Продолжить добавлять части", "ps:v106_brief_status")],
        [("❌ Отменить проект", "ps:cancel")],
    ])


def _duplicate_kb(mod, number: int):
    return mod._kb([
        [(f"♻️ Заменить часть {number}", f"ps:v106_brief_replace:{number}")],
        [("Оставить прежнюю часть", "ps:v106_brief_status")],
        [("❌ Отменить проект", "ps:cancel")],
    ])


def _diagnostics(mod, text: str) -> dict[str, int]:
    products = []
    services = []
    contacts = []
    with contextlib.suppress(Exception):
        products = list(mod._product_offer_objects(text) or [])
    with contextlib.suppress(Exception):
        services = list(mod._service_offer_objects(text) or [])
    with contextlib.suppress(Exception):
        contacts = list(mod._extract_contacts(text) or [])

    benefits: list[str] = []
    stages: list[str] = []
    with contextlib.suppress(Exception):
        benefits = list(mod._v103_section_items(text, ["ключевые преимущества", "преимущества"], 20) or [])
    with contextlib.suppress(Exception):
        stages = list(mod._v103_section_items(text, ["этапы работы", "этапы реализации"], 30) or [])

    return {
        "products": len(products),
        "services": len(services),
        "contacts": len(contacts),
        "benefits": len(benefits),
        "stages": len(stages),
    }


def _status_text(mod, project: dict[str, Any]) -> str:
    parts = _parts(project)
    expected = _expected(project)
    missing = _missing(project)
    text = _combined(project)
    diag = _diagnostics(mod, text)
    received = ", ".join(map(str, sorted(parts))) or "—"
    expected_text = str(expected) if expected else "не задано"
    missing_text = ", ".join(map(str, missing)) if missing else "нет"
    state = "все заявленные части получены" if _complete(project) else "бриф ещё собирается"
    return (
        "📊 Статус главного брифа\n\n"
        f"Получены части: {received}\n"
        f"Ожидалось частей: {expected_text}\n"
        f"Отсутствуют: {missing_text}\n"
        f"Общий объём: {len(text)} символов\n"
        f"Состояние: {state}\n\n"
        "Предварительно распознано без завершения брифа:\n"
        f"• продукты: {diag['products']}\n"
        f"• сервисные пакеты: {diag['services']}\n"
        f"• контакты: {diag['contacts']}\n"
        f"• преимущества: {diag['benefits']}\n"
        f"• этапы: {diag['stages']}\n\n"
        "Проверка не завершает бриф и не создаёт структуру."
    )


async def _reply_saved(mod, update, project: dict[str, Any], number: int) -> None:
    parts = _parts(project)
    expected = _expected(project)
    total_chars = len(_combined(project))
    if expected:
        missing = _missing(project)
        if not missing:
            message = (
                f"✅ Часть {number} из {expected} сохранена.\n"
                f"Получены все {expected} части. Общий объём: {total_chars} символов.\n\n"
                "Бриф ещё не анализирую. Проверьте полученные части и нажмите "
                "«Подтвердить и распознать бриф»."
            )
        else:
            next_part = missing[0]
            message = (
                f"✅ Часть {number} из {expected} сохранена.\n"
                f"Получено частей: {len(parts)} из {expected}. Общий объём: {total_chars} символов.\n\n"
                f"Жду часть {next_part} из {expected}. Бриф ещё не анализирую и структуру не создаю."
            )
    else:
        message = (
            f"✅ Часть {number} сохранена. Общий объём: {total_chars} символов.\n\n"
            "Можно отправить следующую часть. Когда закончите, нажмите «Завершить досрочно». "
            "До подтверждения структура не создаётся."
        )
    await mod._reply(update, message, _brief_kb(mod, project))


async def _collect_text(mod, update, context, project: dict[str, Any], text: str) -> bool:
    text = (text or "").strip()
    if not text:
        return True

    number, total = _parse_part_marker(text)
    parts = _parts(project)
    expected = _expected(project)

    if total:
        if expected and expected != total:
            await mod._reply(
                update,
                f"В проекте уже зафиксировано {expected} частей, а в новом сообщении указано {total}. "
                "Исправьте номер части либо очистите бриф и начните заново.",
                _brief_kb(mod, project),
            )
            return True
        project["brief_v106_expected_parts"] = total
        expected = total
    if number is None:
        number = (max(parts) + 1) if parts else 1

    clean = _clean_part_text(text)
    if len(clean) < 30:
        await mod._reply(update, "Эта часть слишком короткая. Пришлите содержательный фрагмент брифа.", _brief_kb(mod, project))
        return True

    if number in parts and parts[number] != clean:
        project["brief_v106_pending_replace"] = {"number": number, "text": clean}
        project["stage"] = COLLECT_STAGE
        project["brief_v106_active"] = True
        mod._save(project["user_id"], project)
        await mod._reply(
            update,
            f"Часть {number} уже сохранена и отличается от новой версии. Заменить её?",
            _duplicate_kb(mod, number),
        )
        return True

    parts[number] = clean
    _write_parts(project, parts)
    project["stage"] = COLLECT_STAGE
    project["brief_v106_active"] = True
    project["raw_brief"] = _combined(project)
    project.pop("brief_v106_pending_replace", None)
    mod._save(project["user_id"], project)
    context.user_data["presentation_studio_active"] = project.get("project_id")
    await _reply_saved(mod, update, project, number)
    return True


async def _finalize(mod, update, context, project: dict[str, Any], allow_incomplete: bool = False) -> None:
    missing = _missing(project)
    if missing and not allow_incomplete:
        await mod._reply(
            update,
            "Нельзя начать анализ: отсутствуют части " + ", ".join(map(str, missing)) + ".",
            _brief_kb(mod, project),
        )
        return
    combined = _combined(project)
    if len(combined) < 80:
        await mod._reply(update, "Главный бриф слишком короткий. Добавьте сведения о проекте.", _brief_kb(mod, project))
        return

    project["raw_brief"] = combined
    project["stage"] = PROCESS_STAGE
    project["brief_v106_active"] = False
    mod._save(project["user_id"], project)
    await mod._reply(
        update,
        f"✅ Главный бриф объединён: {len(_parts(project))} частей, {len(combined)} символов.\n"
        "Теперь распознаю факты и создаю структуру…",
    )

    project["profile"] = await mod._parse_profile(combined, update)
    if not mod._is_valid_brand_name(project.get("profile", {}).get("brand_name", "")):
        project["stage"] = "await_brand_name"
        mod._save(project["user_id"], project)
        await mod._reply(update, "Не удалось надёжно определить название. Пришлите только точное название бренда.")
        return

    project["structure"] = await mod._generate_structure(project, update)
    project["stage"] = "structure_review"
    project["brief_v106_finalized"] = True
    mod._save(project["user_id"], project)
    context.user_data["presentation_studio_active"] = project.get("project_id")
    await mod._reply(update, mod._structure_text(project), mod.STRUCTURE_KB)


def patch_module(mod) -> None:
    if getattr(mod, "_V106_MULTIPART_PATCHED", False):
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
        if stage in _BRIEF_STAGES or project.get("brief_v106_active"):
            return await _collect_text(mod, update, context, project, text)
        return await original_handle_text(self, update, context, text)

    async def handle_callback(self, update, context) -> bool:
        q = update.callback_query
        data = (q.data or "") if q else ""
        legacy_map = {
            "ps:brief_finish": "ps:v106_brief_finish",
            "ps:brief_done": "ps:v106_brief_finish",
            "ps:finish_brief": "ps:v106_brief_finish",
            "ps:brief_complete": "ps:v106_brief_finish",
            "ps:brief_finalize": "ps:v106_brief_finish",
            "ps:brief_status": "ps:v106_brief_status",
            "ps:brief_check": "ps:v106_brief_status",
            "ps:brief_parts_status": "ps:v106_brief_status",
            "ps:brief_clear": "ps:v106_brief_clear",
            "ps:brief_reset": "ps:v106_brief_clear",
        }
        data = legacy_map.get(data, data)
        if not data.startswith("ps:v106_brief_"):
            return await original_handle_callback(self, update, context)
        with contextlib.suppress(Exception):
            await q.answer()
        project = mod._load(q.from_user.id)
        if not project:
            await mod._reply(update, "Проект не найден. Создайте новый проект.")
            return True
        action = data[len("ps:"):]

        if action == "v106_brief_status":
            project["stage"] = COLLECT_STAGE
            project["brief_v106_active"] = True
            mod._save(project["user_id"], project)
            await mod._reply(update, _status_text(mod, project), _brief_kb(mod, project))
        elif action == "v106_brief_clear":
            project["brief_v106_parts"] = {}
            project["brief_v106_expected_parts"] = 0
            project["brief_v106_active"] = True
            project["raw_brief"] = ""
            project["stage"] = COLLECT_STAGE
            project.pop("brief_v106_pending_replace", None)
            mod._save(project["user_id"], project)
            await mod._reply(
                update,
                "Главный бриф очищен. Отправьте первую часть. Анализ начнётся только после явного подтверждения.",
                _brief_kb(mod, project),
            )
        elif action == "v106_brief_finish":
            await _finalize(mod, update, context, project, allow_incomplete=False)
        elif action == "v106_brief_finish_early":
            missing = _missing(project)
            warning = (
                "Не все заявленные части получены: " + ", ".join(map(str, missing)) + ".\n\n"
                if missing else
                "Количество частей заранее не было указано.\n\n"
            )
            await mod._reply(
                update,
                warning + "Досрочное завершение может привести к потере продуктов, цен или контактов. Подтвердить?",
                _confirm_early_kb(mod),
            )
        elif action == "v106_brief_finish_early_confirm":
            await _finalize(mod, update, context, project, allow_incomplete=True)
        elif action.startswith("v106_brief_replace:"):
            try:
                number = int(action.rsplit(":", 1)[1])
            except Exception:
                number = 0
            pending = project.get("brief_v106_pending_replace") or {}
            if number <= 0 or int(pending.get("number") or 0) != number or not pending.get("text"):
                await mod._reply(update, "Новая версия части не найдена.", _brief_kb(mod, project))
            else:
                parts = _parts(project)
                parts[number] = str(pending["text"]).strip()
                _write_parts(project, parts)
                project.pop("brief_v106_pending_replace", None)
                project["raw_brief"] = _combined(project)
                project["stage"] = COLLECT_STAGE
                project["brief_v106_active"] = True
                mod._save(project["user_id"], project)
                await _reply_saved(mod, update, project, number)
        return True

    mod.PresentationStudio.handle_text = handle_text
    mod.PresentationStudio.handle_callback = handle_callback
    mod._V106_MULTIPART_PATCHED = True
    mod.PRESENTATION_PATCH_VERSION = VERSION


def patch_main_version_async() -> None:
    def worker() -> None:
        # main.py is still importing when this function is called. Re-apply for a
        # short window so older version hooks cannot win a race.
        for _ in range(600):
            for name in ("__main__", "main"):
                module = sys.modules.get(name)
                if module is not None:
                    with contextlib.suppress(Exception):
                        setattr(module, "PATCH_VERSION", VERSION)
            time.sleep(0.1)

    thread = threading.Thread(target=worker, name="presentation-v106-version", daemon=True)
    thread.start()


__all__ = ["VERSION", "patch_module", "patch_main_version_async"]
