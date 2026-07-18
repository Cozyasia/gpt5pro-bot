# -*- coding: utf-8 -*-
"""Neyro-Bot v118 quality release.

This runtime patch closes two production gaps without rewriting main.py:
1) a guaranteed post-analysis Medical Card decision (save/create for entitled
   users, contextual PRO/ULTIMATE offer for everyone else);
2) strict isolation and source fidelity for PDF/PPTX projects, including exact
   brand-name extraction and preservation of an explicitly supplied slide plan.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import re
import sys
import threading
import time
from typing import Any

VERSION = "v118-medcard-presentation-quality-2026-07-18"
_MEDICAL_FLAG = "_V118_MEDCARD_OFFER_PATCHED"
_PRESENTATION_FLAG = "_V118_PRESENTATION_QUALITY_PATCHED"
_DEDUPE_TTL_SECONDS = 15 * 60

UPSELL_TEXT = (
    "📁 Добавьте этот результат в персональную медицинскую карту\n\n"
    "Медицинская карта доступна в тарифах PRO и ULTIMATE. Она позволяет:\n"
    "• хранить оригиналы анализов, заключений, УЗИ, МРТ и КТ;\n"
    "• сохранять распознанные показатели и подробные разборы;\n"
    "• видеть хронологию и динамику по датам;\n"
    "• вести отдельные профили для себя и близких;\n"
    "• искать документы и формировать PDF-сводку для врача.\n\n"
    "Этот разбор останется в чате. После перехода на PRO или ULTIMATE новые "
    "медицинские материалы можно сохранять в карту сразу после анализа."
)

STANDARD_DISCLAIMER = (
    "⚠️ Важно: это справочный разбор и подготовка вопросов к врачу, а не диагноз, "
    "не медицинское заключение и не замена очной консультации или обследования."
)


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _log(mod: Any, level: str, message: str, *args: Any) -> None:
    logger = getattr(mod, "log", None)
    fn = getattr(logger, level, None) if logger is not None else None
    if callable(fn):
        with contextlib.suppress(Exception):
            fn(message, *args)


def _eligible(card: Any, mod: Any, user: Any) -> bool:
    with contextlib.suppress(Exception):
        if bool(card._eligible(mod, user)):
            return True
    uid = int(getattr(user, "id", 0) or 0)
    username = str(getattr(user, "username", "") or "")
    checker = getattr(mod, "is_unlimited", None)
    if callable(checker):
        with contextlib.suppress(Exception):
            if bool(checker(uid, username)):
                return True
    return bool(uid and uid == int(getattr(mod, "OWNER_ID", 0) or 0))


def _pending_signature(pending: Any) -> str:
    if not isinstance(pending, dict):
        return ""
    digest = hashlib.sha256()
    for key in ("track", "source_type", "filename", "mime_type", "created_ts"):
        digest.update(str(pending.get(key) or "").encode("utf-8", errors="ignore"))
        digest.update(b"\0")
    raw = pending.get("file_bytes") or b""
    if isinstance(raw, bytearray):
        raw = bytes(raw)
    if isinstance(raw, bytes):
        digest.update(str(len(raw)).encode("ascii"))
        digest.update(raw[:65536])
    digest.update(str(pending.get("analysis") or "")[:4096].encode("utf-8", errors="ignore"))
    return digest.hexdigest()[:24]


def _recently_sent(context: Any, signature: str) -> bool:
    if not signature:
        return False
    state = context.user_data.get("medcard_v118_last_offer") or {}
    if not isinstance(state, dict):
        return False
    return (
        state.get("signature") == signature
        and time.time() - float(state.get("timestamp") or 0) < _DEDUPE_TTL_SECONDS
    )


def _mark_sent(context: Any, signature: str, kind: str) -> None:
    context.user_data["medcard_v118_last_offer"] = {
        "signature": signature,
        "timestamp": time.time(),
        "kind": kind,
    }


def _upsell_kb(card: Any, mod: Any):
    return card._kb(
        mod,
        [
            [("🚀 Подключить PRO", "plan:pro"), ("💎 Подключить ULTIMATE", "plan:ultimate")],
            [("ℹ️ Сравнить тарифы", "plan:root")],
            [("⬅️ Вернуться в Медицину", "medcard:back_med")],
        ],
    )


def _dedupe_disclaimer(answer: str) -> str:
    text = str(answer or "").strip()
    if not text:
        return text
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    kept: list[str] = []
    for paragraph in paragraphs:
        low = paragraph.lower().replace("ё", "е")
        disclaimer_like = (
            ("не является диагноз" in low or "не заменяет" in low or "справочн" in low)
            and ("врач" in low or "консультац" in low or "обследован" in low)
        )
        if disclaimer_like:
            continue
        kept.append(paragraph)
    kept.append(STANDARD_DISCLAIMER)
    return "\n\n".join(kept).strip()


async def _medical_offer(mod: Any, update: Any, context: Any) -> None:
    """Guaranteed final Medical Card decision after a successful analysis."""
    try:
        import medical_card_v109_patch as card
    except Exception as exc:
        _log(mod, "warning", "v118 medical-card import failed: %r", exc)
        return

    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    pending = context.user_data.get("medcard_pending") or {}
    if user is None or message is None or not isinstance(pending, dict) or not pending:
        _log(mod, "warning", "v118 medical-card offer skipped: pending=%s", bool(pending))
        return

    uid = int(getattr(user, "id", 0) or 0)
    signature = _pending_signature(pending)
    entitled = _eligible(card, mod, user)

    try:
        if entitled:
            if card._auto_save(mod, uid) and card._has_consent(mod, uid):
                ok, text, doc_id = await card._save_pending(mod, update, context)
                markup = card._card_main_kb(mod)
                if ok and doc_id:
                    row = card._doc_row(mod, uid, doc_id)
                    if row:
                        markup = card._doc_kb(mod, doc_id, bool(row[9]))
                await message.reply_text(text, reply_markup=markup)
                _mark_sent(context, signature, "auto_saved" if ok else "auto_save_error")
                return

            await message.reply_text(
                "📁 Сохранить оригинал, распознанные данные и этот разбор в медицинскую карту?",
                reply_markup=card._pending_save_kb(mod, uid),
            )
            _mark_sent(context, signature, "save_prompt")
            context.user_data["medcard_offer_last_status"] = "entitled_prompt_sent"
            return

        if _recently_sent(context, signature):
            return
        await message.reply_text(
            UPSELL_TEXT,
            reply_markup=_upsell_kb(card, mod),
            disable_web_page_preview=True,
        )
        context.user_data.pop("medcard_pending", None)
        context.user_data.pop("medcard_source_capture", None)
        _mark_sent(context, signature, "upsell")
        context.user_data["medcard_offer_last_status"] = "upsell_sent"
    except Exception as exc:
        _log(mod, "exception", "v118 medical-card final offer failed: %r", exc)
        context.user_data["medcard_offer_last_status"] = f"error:{type(exc).__name__}"
        with contextlib.suppress(Exception):
            if entitled:
                await message.reply_text(
                    "📁 Медицинская карта доступна вашему аккаунту, но кнопки сохранения не загрузились. "
                    "Откройте «Моя медицинская карта» в меню Медицина и повторите сохранение."
                )
            else:
                await message.reply_text(UPSELL_TEXT, disable_web_page_preview=True)


def _patch_medical() -> bool:
    mod = _runtime_module()
    if mod is None:
        return False
    try:
        import medical_card_v109_patch as card
        import medical_v111_runtime as runtime
        import medical_v114_overlay as overlay
    except Exception:
        return False

    if not getattr(runtime, _MEDICAL_FLAG, False):
        runtime._offer_save = _medical_offer
        card._offer_save = _medical_offer

        original_send = runtime._send_answer
        if not getattr(original_send, "_v118_wrapped", False):
            async def send_answer(mod_arg: Any, update: Any, context: Any, answer: str) -> None:
                await original_send(mod_arg, update, context, _dedupe_disclaimer(answer))
            send_answer._v118_wrapped = True
            send_answer._v118_original = original_send
            runtime._send_answer = send_answer

        rules = """

V118 CLINICAL PRECISION RULES
• A combined label such as TI-RADS 3–4 is an ambiguous source classification, not a single category. State that the exact system and one final category must be clarified. Biopsy or surveillance thresholds may be discussed only conditionally and must be tied to the named guideline system, exact maximal diameter, morphology and clinical context.
• Never say that a low-risk category completely or practically excludes malignancy. Use calibrated language such as low or very low ultrasound suspicion.
• Describe adenomyosis as ultrasound signs or a working finding unless a clinician has established the diagnosis. Do not recommend MRI automatically; explain when it can change management.
• Do not invent 1–3 or 2–3 month surveillance for a tiny uncomplicated incidental paraovarian/simple cyst. If no source guideline fixes the interval, state that routine observation depends on symptoms, morphology and prior dynamics.
• For thyroid testing, prioritize TSH; add free T4, antibodies, calcitonin or other tests only when they can change management and explain why. Avoid automatic broad panels.
• Give one concise disclaimer at the end, not two repetitive warnings.
"""
        audit_rules = """

V118 FINAL AUDIT
• Reject absolute claims that TI-RADS 2 excludes cancer.
• Reject a definitive TI-RADS threshold unless the classification system is named and the recommendation is conditional.
• Reject arbitrary short follow-up intervals for a tiny uncomplicated cyst.
• Reject automatic broad thyroid hormone panels and automatic pelvic MRI.
• Ensure adenomyosis is described as ultrasound signs unless the source explicitly contains a confirmed clinical diagnosis.
• Ensure only one final medical disclaimer remains.
"""
        if "V118 CLINICAL PRECISION RULES" not in overlay.REASON_SYSTEM:
            overlay.REASON_SYSTEM += rules
        if "V118 FINAL AUDIT" not in overlay.AUDIT_SYSTEM:
            overlay.AUDIT_SYSTEM += audit_rules

        setattr(runtime, _MEDICAL_FLAG, True)

    mod.MEDICAL_CARD_VERSION = VERSION
    mod.MEDICAL_PATCH_VERSION = VERSION
    mod.PATCH_VERSION = VERSION
    setattr(mod, _MEDICAL_FLAG, True)
    return True


_PROJECT_NAME_PATTERNS = (
    re.compile(r"(?im)^\s*(?:название\s+проекта|проект)\s*[:—-]\s*([^\n]{2,100})$"),
    re.compile(r"(?i)\b(?:презентац(?:ию|ия)|каталог)\s+для\s+проекта\s+[«\"']?([^\n.;]{2,100})"),
    re.compile(r"(?i)\bдля\s+проекта\s+[«\"']?([^\n.;]{2,100})"),
)


def _clean_name(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip(" \n\t:—-.,;\"'«»")
    value = re.split(r"\s{2,}|\b(?:формат|язык|аудитория|стиль|цвета|структура)\s*:", value, maxsplit=1, flags=re.I)[0]
    return value.strip(" :—-.,;\"'«»")[:100]


def _project_name_from_prose(text: str) -> str:
    for pattern in _PROJECT_NAME_PATTERNS:
        match = pattern.search(text or "")
        if match:
            candidate = _clean_name(match.group(1))
            if len(candidate) >= 2 and re.search(r"[A-Za-zА-Яа-яЁё]", candidate):
                return candidate
    return ""


def _explicit_slide_plan(raw: str, brand: str = "") -> list[dict[str, Any]]:
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    start = -1
    for idx, line in enumerate(lines):
        if re.match(r"^\s*(?:структура|план\s+слайдов|слайды)\s*:\s*$", line, re.I):
            start = idx + 1
            break
    if start < 0:
        return []

    items: list[tuple[int, str, list[str]]] = []
    current_num = 0
    current_title = ""
    current_body: list[str] = []

    def flush() -> None:
        nonlocal current_num, current_title, current_body
        if current_num and current_title:
            items.append((current_num, current_title, list(current_body)))
        current_num, current_title, current_body = 0, "", []

    for line in lines[start:]:
        stripped = line.strip()
        match = re.match(r"^(\d{1,2})[.)]\s*(.+?)\s*$", stripped)
        if match:
            flush()
            current_num = int(match.group(1))
            current_title = match.group(2).strip(" —-")
            continue
        if current_num:
            if re.match(r"^[A-Za-zА-Яа-яЁё][^.!?]{1,45}:$", stripped) and not re.match(r"^(?:текст|содержание|подзаголовок):$", stripped, re.I):
                flush()
                break
            if stripped:
                current_body.append(stripped)
    flush()

    if len(items) < 6:
        return []
    numbers = [item[0] for item in items]
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        return []

    result: list[dict[str, Any]] = []
    for index, (_num, title, body) in enumerate(items):
        low = title.lower().replace("ё", "е")
        slide_title = title
        if index == 0 and ("титуль" in low or "облож" in low):
            slide_title = brand or title
        bullets: list[str] = []
        for chunk in body:
            cleaned = re.sub(r"^[•\-–—]+\s*", "", chunk).strip()
            if not cleaned:
                continue
            for part in re.split(r"\s*;\s*", cleaned):
                part = part.strip()
                if part and part not in bullets:
                    bullets.append(part[:500])
        if index == 0 and brand:
            bullets = [b for b in bullets if b.strip().lower() != brand.strip().lower()]
        if not bullets:
            bullets = ["Содержание — строго по главному брифу"]
        if index == 0:
            layout = "cover"
        elif index == len(items) - 1 or any(token in low for token in ("контакт", "следующий шаг", "cta", "призыв")):
            layout = "cta"
        elif any(token in low for token in ("тариф", "пакет", "линейк", "сравнен")):
            layout = "comparison"
        elif any(token in low for token in ("как это работает", "этап", "процесс", "схема")):
            layout = "process"
        else:
            layout = "cards" if len(bullets) >= 3 else "split"
        result.append({
            "title": slide_title[:110],
            "layout": layout,
            "image_needed": layout in {"cover", "split", "comparison", "cta"},
            "bullets": bullets[:6],
            "image_prompt": "",
        })
    return result


def _neutral_fallback(studio: Any, project: dict[str, Any]) -> list[dict[str, Any]]:
    profile = project.get("profile") or {}
    raw = str(project.get("raw_brief") or "")
    brand = str(profile.get("brand_name") or _project_name_from_prose(raw) or "Проект")
    explicit = _explicit_slide_plan(raw, brand)
    if explicit:
        return explicit

    count = int(profile.get("requested_slide_count") or 12)
    count = max(8, min(16, count))
    kind = str(project.get("kind") or "presentation")
    contacts = list(profile.get("contacts") or [])
    prices = list(profile.get("prices") or [])

    if kind == "catalog":
        titles = [
            brand,
            "О компании и формате работы",
            "Ключевые преимущества",
            "Объекты и направления",
            "Условия и стоимость",
            "Как проходит подбор и бронирование",
            "Сервис и сопровождение",
            "Для кого подходит предложение",
            "Контакты и следующий шаг",
        ]
    else:
        titles = [
            brand,
            "Контекст и задача",
            "Проблема пользователя",
            "Решение",
            "Основные направления",
            "Сильные функции",
            "Как это работает",
            "Сценарии использования",
            "Тарифы и условия" if prices or re.search(r"тариф|цена|стоимост", raw, re.I) else "Форматы использования",
            "Технологическая основа" if re.search(r"модел|api|движк|технолог", raw, re.I) else "Ключевые преимущества",
            "Следующий шаг",
        ]

    while len(titles) < count:
        titles.insert(-1, f"Дополнительный раздел {len(titles)}")
    while len(titles) > count:
        titles.pop(-2)

    objective = str(profile.get("objective") or "")
    product = str(profile.get("product") or "")
    audience = str(profile.get("audience") or "")
    positioning = str(profile.get("positioning") or "")
    slides: list[dict[str, Any]] = []
    for idx, title in enumerate(titles):
        if idx == 0:
            bullets = [str(profile.get("tagline") or "Презентация проекта")]
            layout = "cover"
        elif idx == len(titles) - 1:
            bullets = contacts[:4] or ["Следующий шаг определяется после согласования содержания"]
            layout = "cta"
        elif "задач" in title.lower():
            bullets = [value for value in (objective, product) if value][:3] or ["Факты и формулировки — из главного брифа"]
            layout = "split"
        elif "аудитор" in title.lower() or "для кого" in title.lower():
            bullets = [audience] if audience else ["Целевая аудитория — по главному брифу"]
            layout = "cards"
        elif "тариф" in title.lower() or "стоимост" in title.lower():
            bullets = prices[:6] or ["Цены и условия — только из главного брифа"]
            layout = "comparison"
        elif "решение" in title.lower():
            bullets = [value for value in (product, positioning) if value][:3] or ["Решение описывается без вымышленных фактов"]
            layout = "split"
        else:
            bullets = ["Содержание — строго по текущему главному брифу"]
            layout = "process" if any(x in title.lower() for x in ("как", "этап")) else "cards"
        slides.append({
            "title": title[:110],
            "layout": layout,
            "image_needed": layout in {"cover", "split", "comparison", "cta"},
            "bullets": [str(x)[:500] for x in bullets if str(x).strip()][:6],
            "image_prompt": "",
        })
    return slides


def _structure_is_contaminated(project: dict[str, Any], structure: list[dict[str, Any]]) -> bool:
    raw = str(project.get("raw_brief") or "").lower().replace("ё", "е")
    rendered = json.dumps(structure, ensure_ascii=False).lower().replace("ё", "е")
    suspicious = (
        "премиальные решения для интерьера",
        "эмоциональное позиционирование",
        "почему обычные решения не работают",
        "эстетика",
        "архитекторы и дизайнеры",
        "коммерческие пространства",
        "монтаж под ключ",
        "бесплатную консультацию",
    )
    return any(phrase in rendered and phrase not in raw for phrase in suspicious)


def _patch_presentation() -> bool:
    try:
        import presentation_studio as studio
        import presentation_v106_patch as v106
    except Exception:
        return False
    if getattr(studio, _PRESENTATION_FLAG, False):
        return True

    original_extract_brand = studio._extract_brand_name_regex
    def extract_brand(text: str) -> str:
        exact = _project_name_from_prose(text)
        if exact and studio._is_valid_brand_name(exact):
            return exact
        return original_extract_brand(text)
    studio._extract_brand_name_regex = extract_brand

    original_parse_profile = studio._parse_profile
    async def parse_profile(raw_brief: str, update: Any = None) -> dict[str, Any]:
        profile = await original_parse_profile(raw_brief, update)
        exact = _project_name_from_prose(raw_brief) or original_extract_brand(raw_brief)
        if exact and studio._is_valid_brand_name(exact):
            profile["brand_name"] = exact
        explicit = _explicit_slide_plan(raw_brief, profile.get("brand_name", ""))
        if explicit:
            profile["requested_slide_count"] = len(explicit)
        return profile
    studio._parse_profile = parse_profile

    studio._fallback_structure = lambda project: _neutral_fallback(studio, project)

    original_generate = studio._generate_structure
    async def generate_structure(project: dict[str, Any], update: Any = None) -> list[dict[str, Any]]:
        raw = str(project.get("raw_brief") or "")
        profile = project.get("profile") or {}
        brand = str(profile.get("brand_name") or _project_name_from_prose(raw) or "")
        explicit = _explicit_slide_plan(raw, brand)
        if explicit:
            project["structure_source"] = "explicit_user_plan"
            project["structure_validation"] = {"ok": True, "reason": "explicit_plan", "count": len(explicit)}
            return explicit

        generated = await original_generate(project, update)
        target = int(profile.get("requested_slide_count") or 12)
        target = max(8, min(16, target))
        invalid = not isinstance(generated, list) or len(generated) != target or _structure_is_contaminated(project, generated)
        if brand and generated:
            first_title = str(generated[0].get("title") or "")
            if brand.lower() not in first_title.lower():
                generated[0]["title"] = brand
        if invalid:
            generated = _neutral_fallback(studio, project)
            project["structure_source"] = "v118_neutral_fallback"
            project["structure_validation"] = {"ok": False, "reason": "count_or_contamination", "count": len(generated)}
        else:
            project["structure_source"] = "llm_validated"
            project["structure_validation"] = {"ok": True, "reason": "validated", "count": len(generated)}
        return generated
    studio._generate_structure = generate_structure

    original_new_project = studio._new_project
    def new_project(user_id: int, kind: str = "presentation", chat_id: int = 0) -> dict[str, Any]:
        project = original_new_project(user_id, kind, chat_id)
        project.update({
            "raw_brief": "",
            "profile": {},
            "structure": [],
            "structure_notes": [],
            "visual_notes": [],
            "style_notes": [],
            "palette_notes": [],
            "logo_notes": [],
            "logo_candidates": [],
            "uploaded_images": [],
            "slide_images": {},
            "brief_v106_parts": {},
            "brief_v106_expected_parts": 0,
            "brief_v106_active": True,
            "brief_v106_finalized": False,
            "structure_source": "",
            "structure_validation": {},
        })
        return project
    studio._new_project = new_project

    def brief_kb(mod: Any, project: dict[str, Any]):
        if v106._complete(project):
            primary = ("✅ Завершить ввод и распознать бриф", "ps:v106_brief_finish")
        else:
            primary = ("✅ Завершить ввод главного брифа", "ps:v106_brief_finish_early")
        return mod._kb([
            [primary],
            [("📊 Проверить объём и разделы", "ps:v106_brief_status")],
            [("🧹 Очистить и ввести заново", "ps:v106_brief_clear")],
            [("❌ Отменить проект", "ps:cancel")],
        ])
    v106._brief_kb = brief_kb

    def confirm_kb(mod: Any):
        return mod._kb([
            [("✅ Да, завершить текущий бриф", "ps:v106_brief_finish_early_confirm")],
            [("↩️ Продолжить добавлять части", "ps:v106_brief_status")],
            [("❌ Отменить проект", "ps:cancel")],
        ])
    v106._confirm_early_kb = confirm_kb

    async def reply_saved(mod: Any, update: Any, project: dict[str, Any], number: int) -> None:
        parts = v106._parts(project)
        expected = v106._expected(project)
        total_chars = len(v106._combined(project))
        if expected:
            missing = v106._missing(project)
            if missing:
                message = (
                    f"✅ Часть {number} из {expected} сохранена.\n"
                    f"Получено частей: {len(parts)} из {expected}. Общий объём: {total_chars} символов.\n\n"
                    f"Жду часть {missing[0]} из {expected}. Структура до подтверждения не создаётся."
                )
            else:
                message = (
                    f"✅ Часть {number} из {expected} сохранена. Получены все части. "
                    f"Общий объём: {total_chars} символов.\n\n"
                    "Проверьте объём и нажмите «Завершить ввод и распознать бриф»."
                )
        else:
            message = (
                f"✅ Часть {number} сохранена. Общий объём: {total_chars} символов.\n\n"
                "Можно отправить следующую часть. Когда закончите, нажмите "
                "«Завершить ввод главного брифа». До подтверждения структура не создаётся."
            )
        await mod._reply(update, message, brief_kb(mod, project))
    v106._reply_saved = reply_saved

    studio.PRESENTATION_PATCH_VERSION = VERSION
    setattr(studio, _PRESENTATION_FLAG, True)
    return True


def patch_runtime() -> bool:
    medical = _patch_medical()
    presentation = _patch_presentation()
    mod = _runtime_module()
    if mod is not None and (medical or presentation):
        mod.PATCH_VERSION = VERSION
        mod.MEDICAL_CARD_VERSION = VERSION
        mod.PRESENTATION_PATCH_VERSION = VERSION
    return medical and presentation


def install_async() -> None:
    def worker() -> None:
        patched = False
        for _ in range(15000):
            with contextlib.suppress(Exception):
                if patch_runtime():
                    patched = True
                    break
            time.sleep(0.02)
        if patched:
            mod = _runtime_module()
            for _ in range(2100):
                if mod is not None:
                    with contextlib.suppress(Exception):
                        mod.PATCH_VERSION = VERSION
                        mod.MEDICAL_CARD_VERSION = VERSION
                        mod.PRESENTATION_PATCH_VERSION = VERSION
                time.sleep(0.2)

    threading.Thread(target=worker, daemon=True, name="release-v118-quality").start()


__all__ = ["VERSION", "UPSELL_TEXT", "patch_runtime", "install_async"]
