# -*- coding: utf-8 -*-
"""Neyro-Bot Medical Review v108.

Upgrades the existing medical mode from a shallow transcription into a two-stage,
source-grounded clinical explanation:
1) exact extraction from the uploaded image/document;
2) structured reasoning with priorities, urgency, next steps and questions for a doctor.

The patch is intentionally dependency-free and is applied after main.py finishes
creating the original medical handlers.
"""
from __future__ import annotations

import base64
import contextlib
import os
import re
import sys
import threading
import time
from typing import Any

VERSION = "v108-medical-deep-review-2026-07-17"
_PATCH_FLAG = "_MEDICAL_V108_PATCHED"


def _clean_text(value: str) -> str:
    value = (value or "").replace("\x00", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{4,}", "\n\n\n", value)
    return value.strip()


def _plain_telegram(value: str) -> str:
    """Remove markdown-only decorations that Telegram currently displays literally."""
    value = _clean_text(value)
    value = re.sub(r"(?m)^#{1,6}\s*", "", value)
    value = value.replace("**", "")
    value = re.sub(r"(?m)^\s*[-–—]\s+", "• ", value)
    return value.strip()


def _split_long_text(text: str, limit: int = 3800) -> list[str]:
    text = _plain_telegram(text)
    if not text:
        return ["Не удалось сформировать содержательный медицинский разбор."]
    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind("\n\n", 0, limit)
        if cut < int(limit * 0.45):
            cut = rest.rfind("\n", 0, limit)
        if cut < int(limit * 0.35):
            cut = rest.rfind(". ", 0, limit)
            if cut >= 0:
                cut += 1
        if cut < int(limit * 0.25):
            cut = limit
        chunks.append(rest[:cut].strip())
        rest = rest[cut:].lstrip()
    if rest:
        chunks.append(rest)
    return [chunk for chunk in chunks if chunk]


def _source_label(track: str, source_type: str) -> str:
    mapping = {
        "med_extract": "выписка или анамнез",
        "med_scan": "фото медицинского документа или исследования",
        "med_conclusion": "врачебное заключение",
        "med_mri": "описание или изображение МРТ",
        "med_ct": "описание или изображение КТ",
        "med_labs": "лабораторные анализы",
        "med_free": "медицинский вопрос",
    }
    return mapping.get(track or "", source_type or "медицинский материал")


def _extraction_prompt(track: str, goal: str | None) -> str:
    goal_line = f"\nЦель пользователя: {goal.strip()}" if goal and goal.strip() else ""
    return f"""
Ты выполняешь ПЕРВЫЙ ЭТАП медицинского разбора: точное извлечение данных из изображения.
Тип материала: {_source_label(track, 'изображение')}.

Твоя задача сейчас — не консультировать и не интерпретировать, а максимально точно прочитать источник.

Правила:
1. Перепиши медицински значимый текст: название исследования, дату, органы, размеры, единицы, описания, категории, заключение и рекомендации.
2. Сохраняй числа, десятичные разделители, знаки ×, единицы измерения, стороны «слева/справа», отрицания «не выявлено/без кровотока».
3. Не исправляй противоречия документа молча. Если в источнике написано неоднозначно, сохрани формулировку и пометь: [неоднозначно в оригинале].
4. Нечитаемые места обозначай [неразборчиво], ничего не придумывай.
5. Не повторяй ФИО пациента, номер карты, адрес, телефон клиники, печати и другие персональные данные, если они не нужны для медицинского смысла.
6. Для настоящего рентгеновского, КТ-, МРТ- или УЗ-кадра без текста не пытайся ставить диагноз по одному фото. Опиши технический тип изображения и ограничения.
7. Верни только блок «ИЗВЛЕЧЁННЫЕ ДАННЫЕ» без советов и лечения.
{goal_line}
""".strip()


def _analysis_prompt(source_text: str, track: str, goal: str | None, source_type: str) -> str:
    goal_line = f"\nПожелание пользователя: {goal.strip()}" if goal and goal.strip() else ""
    return f"""
Ты — медицинский аналитик и редактор пациентских разъяснений. Подготовь глубокий, практичный и осторожный справочный разбор на русском языке строго по данным источника.

Тип материала: {_source_label(track, source_type)}.
{goal_line}

КЛЮЧЕВАЯ ЗАДАЧА
Не пересказывай документ построчно. Определи клинически значимые находки, расставь их по приоритету, объясни простыми словами, насколько они обычно опасны, что влияет на дальнейшую тактику и что человеку делать дальше.

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА ДОСТОВЕРНОСТИ
• Не придумывай симптомы, диагнозы, анализы, возраст, беременность, лекарства или анамнез, которых нет в источнике.
• Чётко разделяй: «в документе указано», «это обычно означает», «для решения не хватает данных».
• Не называй вероятный диагноз установленным, если это только УЗ-признак, категория риска или предположение врача.
• Не делай вывод о доброкачественности или злокачественности только по фотографии документа.
• Не назначай конкретный препарат, дозу, отмену лекарства или самостоятельное лечение.
• Можно описывать стандартные варианты обследования и лечения как справочную информацию, обязательно условно: «врач может рассмотреть», «тактика зависит от…».
• Если классификация указана диапазоном или без названия системы, например «TI-RADS 3–4», прямо отметь, что это неоднозначно и требует одной точной категории по указанной системе.
• Порог биопсии, операции, наблюдения или лечения называй только условно и только с названием применимой системы/рекомендаций. Если система не указана или данные неполны, не выдавай один порог как бесспорный.
• Для лабораторных анализов учитывай единицы, референс конкретной лаборатории, пол, возраст, беременность, фазу цикла и лекарства, когда это применимо.
• Для МРТ/КТ/рентгена/УЗИ различай официальный протокол и самостоятельное чтение кадра. Приоритет имеет протокол и очная оценка специалиста.
• Если в документе несколько органов или проблем, разбирай каждую отдельно, но в начале укажи, что важнее.
• Не повторяй ФИО, номер карты и иные персональные данные.

ФОРМАТ ОТВЕТА — БЕЗ MARKDOWN-СИМВОЛОВ ### И **
Используй обычные заголовки с эмодзи и маркированные пункты.

🧭 ГЛАВНОЕ ЗА 30 СЕКУНД
2–5 предложений: есть ли признаки экстренной опасности по представленному документу; какая находка приоритетна; насколько срочно и к какому врачу обращаться.
Не пиши «опасности нет», если источник не позволяет это надёжно определить. Лучше: «по описанию экстренных признаков не указано, но…».

📋 ЧТО ИМЕННО НАПИСАНО В ДОКУМЕНТЕ
Коротко перечисли только ключевые факты, размеры, категории, динамику и важные отрицательные признаки. Не дублируй весь протокол.

🔎 РАЗБОР КАЖДОЙ ЗНАЧИМОЙ НАХОДКИ
Для каждой отдельной находки дай:
• что это означает простыми словами;
• насколько обычно тревожно и какие признаки успокаивают/настораживают;
• что в формулировке документа неясно или требует перепроверки;
• что обычно делают дальше и в какие разумные сроки;
• какие методы лечения в принципе существуют, но только если они действительно относятся к этой находке и зависят от симптомов/подтверждения.

✅ ПЛАН ДЕЙСТВИЙ
Раздели на:
• сейчас / ближайшие дни;
• ближайшие 2–4 недели;
• дальнейшее наблюдение.
Указывай специалистов, обследования и цель каждого шага. Не перегружай ненужными анализами.

🚑 КОГДА НУЖНО ОБРАЩАТЬСЯ СРОЧНО
Перечисли только действительно относящиеся к материалу красные флаги. Если специфических красных флагов из источника не следует, так и скажи и дай краткие универсальные признаки резкого ухудшения.

❓ ЧТО СПРОСИТЬ У ВРАЧА
5–10 конкретных вопросов, привязанных к находкам и неоднозначностям документа.

🧩 ЧЕГО НЕ ХВАТАЕТ ДЛЯ ТОЧНОЙ ОЦЕНКИ
Перечисли симптомы, предыдущие исследования, лекарства, планы беременности, фазу цикла или анализы — только те, которые реально могут изменить выводы.
В самом конце задай пользователю 2–5 наиболее важных уточняющих вопросов.

⚠️ БЕЗОПАСНОСТЬ
Заверши коротким предупреждением: это справочный разбор документа и подготовка к консультации, а не диагноз и не замена врача.

ИСТОЧНИК ДЛЯ АНАЛИЗА:
{source_text[:24000]}
""".strip()


def _review_prompt(source_text: str, draft: str) -> str:
    return f"""
Ты — старший медицинский редактор. Проверь черновик ответа по исходному медицинскому тексту и выпусти окончательную улучшенную версию.

Проверь обязательно:
• все ли важные находки и размеры учтены;
• правильно ли расставлен приоритет;
• нет ли выдуманных фактов и чрезмерно уверенных диагнозов;
• не потеряны ли отрицательные благоприятные признаки;
• объяснена ли неоднозначная классификация;
• есть ли конкретный план со сроками, красные флаги и вопросы врачу;
• не подменяет ли ответ врача и не содержит ли самостоятельных назначений;
• нет ли сырого Markdown: символов ###, ** и таблиц.

Исправь ошибки, убери повторения и верни только готовый ответ на русском языке. Сохрани точные числа из источника.

ИСХОДНЫЕ ДАННЫЕ:
{source_text[:18000]}

ЧЕРНОВИК:
{draft[:14000]}
""".strip()


async def _reason(mod: Any, source_text: str, track: str, goal: str | None, source_type: str) -> str:
    source_text = _clean_text(source_text)
    if len(source_text) < 20:
        return (
            "Не удалось надёжно прочитать медицинские данные. Пришлите более чёткое фото без бликов, "
            "снятое строго сверху, либо загрузите PDF/текст заключения."
        )
    draft = await mod.ask_openai_text(_analysis_prompt(source_text, track, goal, source_type))
    draft = _plain_telegram(draft)
    second_pass = os.environ.get("MEDICAL_SECOND_PASS", "1").strip().lower() not in {"0", "false", "no", "off"}
    if second_pass and draft and "не получилось получить ответ" not in draft.lower():
        with contextlib.suppress(Exception):
            reviewed = await mod.ask_openai_text(_review_prompt(source_text, draft))
            reviewed = _plain_telegram(reviewed)
            if len(reviewed) >= 500:
                draft = reviewed
    return draft


async def _send_answer(mod: Any, update: Any, context: Any, answer: str) -> None:
    disclaimer = getattr(mod, "MEDICAL_DISCLAIMER", "").strip()
    answer = _plain_telegram(answer)
    if disclaimer and "справочный разбор" not in answer.lower()[-800:]:
        answer = answer.rstrip() + "\n\n" + disclaimer
    chunks = _split_long_text(answer)
    kb = None
    with contextlib.suppress(Exception):
        kb = mod.medicine_kb()
    for index, chunk in enumerate(chunks):
        kwargs = {}
        if index == len(chunks) - 1 and kb is not None:
            kwargs["reply_markup"] = kb
        await update.effective_message.reply_text(chunk, **kwargs)
    with contextlib.suppress(Exception):
        await mod.maybe_tts_reply(update, context, answer[: getattr(mod, "TTS_MAX_CHARS", 1000)])


def patch_module(mod: Any) -> bool:
    if getattr(mod, _PATCH_FLAG, False):
        setattr(mod, "PATCH_VERSION", VERSION)
        return True
    required = ["ask_openai_text", "ask_openai_vision", "_mode_track_get", "sniff_image_mime"]
    if not all(hasattr(mod, name) for name in required):
        return False

    async def medical_analyze_text(update, context, text: str, goal: str | None = None):
        user_id = update.effective_user.id
        track = mod._mode_track_get(user_id)
        await update.effective_message.reply_text(
            "🩺 Читаю документ и готовлю подробный разбор: выделю главное, риски, сроки и план действий…"
        )
        answer = await _reason(mod, text, track, goal, "текст медицинского документа")
        await _send_answer(mod, update, context, answer)

    async def medical_analyze_image(update, context, img_bytes: bytes, goal: str | None = None):
        user_id = update.effective_user.id
        track = mod._mode_track_get(user_id)
        await update.effective_message.reply_text(
            "🩺 Сначала точно считываю медицинский текст и показатели, затем отдельно проверю их смысл и приоритет…"
        )
        b64 = base64.b64encode(img_bytes).decode("ascii")
        extracted = await mod.ask_openai_vision(
            _extraction_prompt(track, goal), b64, mod.sniff_image_mime(img_bytes)
        )
        extracted = _clean_text(extracted)
        if not extracted or extracted.lower().startswith("не удалось проанализировать"):
            answer = (
                "Не удалось надёжно прочитать изображение. Сделайте фото строго сверху, без бликов и теней, "
                "чтобы весь текст занимал кадр, либо загрузите PDF/текст заключения."
            )
        else:
            await update.effective_message.reply_text(
                "✅ Данные считаны. Формирую клинически значимый разбор без простого пересказа…"
            )
            answer = await _reason(mod, extracted, track, goal, "изображение медицинского документа")
        await _send_answer(mod, update, context, answer)

    def medical_capability_text() -> str:
        return (
            "Да, могу сделать подробный справочный разбор медицинского документа, а не просто переписать его.\n\n"
            "Что получите:\n"
            "• главное и уровень срочности;\n"
            "• точные находки, размеры и категории;\n"
            "• объяснение простыми словами;\n"
            "• разбор каждой проблемы по приоритету;\n"
            "• план действий со сроками;\n"
            "• красные флаги;\n"
            "• вопросы врачу и недостающие данные.\n\n"
            "Поддерживаются выписки, заключения, лабораторные анализы, УЗИ, МРТ, КТ, рентген и фото документов. "
            "По одному кадру исследования бот не заменяет врача-рентгенолога и официальный протокол."
            + getattr(mod, "MEDICAL_DISCLAIMER", "")
        )

    def medical_menu_text(track: str = "") -> str:
        title = _source_label(track, "медицинский документ или снимок")
        return (
            f"🩺 Медицина — готов подробно разобрать {title}.\n\n"
            "Загрузите PDF/DOCX/TXT или чёткое фото. В подписи можно указать цель: «подробно», "
            "«насколько опасно», «что делать дальше», «сравни с предыдущим исследованием».\n\n"
            "Разбор проходит в два этапа: сначала точное извлечение фактов, затем оценка приоритетов, "
            "рисков, сроков обращения, вариантов дальнейшей тактики и вопросов врачу."
            + getattr(mod, "MEDICAL_DISCLAIMER", "")
        )

    mod._medical_analyze_text = medical_analyze_text
    mod._medical_analyze_image = medical_analyze_image
    mod._medical_capability_text = medical_capability_text
    mod._medical_menu_text = medical_menu_text
    setattr(mod, _PATCH_FLAG, True)
    setattr(mod, "MEDICAL_PATCH_VERSION", VERSION)
    setattr(mod, "PATCH_VERSION", VERSION)
    return True


def install_async() -> None:
    """Patch main after its medical functions are defined; keep v108 as visible version."""
    def worker() -> None:
        patched = False
        for _ in range(1800):
            for name in ("__main__", "main"):
                mod = sys.modules.get(name)
                if mod is None:
                    continue
                with contextlib.suppress(Exception):
                    if patch_module(mod):
                        patched = True
            if patched:
                break
            time.sleep(0.1)

        for _ in range(1800):
            for name in ("__main__", "main"):
                mod = sys.modules.get(name)
                if mod is not None:
                    with contextlib.suppress(Exception):
                        setattr(mod, "PATCH_VERSION", VERSION)
            time.sleep(0.1)

    threading.Thread(target=worker, name="medical-v108-patch", daemon=True).start()


__all__ = ["VERSION", "patch_module", "install_async"]
