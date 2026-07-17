# -*- coding: utf-8 -*-
"""Medical Card v110 reliability and clinical-quality patch.

Fixes:
* robust document persistence after the v109 KeyError seen in production;
* strict normalization of AI-produced metadata before SQLite insertion;
* direct routing of photos/documents while the active top-level mode is Medicine;
* safer thyroid/gynecology wording and exact numeric cross-checks;
* stable visible release version after the v108/v109 patch chain.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

VERSION = "v110-medical-card-save-routing-quality-2026-07-18"
_PATCH_FLAG = "_MEDICAL_CARD_V110_PATCHED"
_INSTALLED = False


def _log_exception(mod: Any, message: str, exc: BaseException) -> None:
    logger = getattr(mod, "log", None)
    if logger is not None:
        with contextlib.suppress(Exception):
            logger.error("%s: %s\n%s", message, repr(exc), traceback.format_exc())
            return
    with contextlib.suppress(Exception):
        print(f"{message}: {exc!r}\n{traceback.format_exc()}", file=sys.stderr)


def _dict_items(value: Any, limit: int) -> list[dict]:
    """Accept a list, one object, or a keyed object returned by an LLM."""
    if isinstance(value, list):
        return [item for item in value[:limit] if isinstance(item, dict)]
    if isinstance(value, dict):
        # A single structured item.
        if any(key in value for key in ("name", "label", "title", "dosage", "value_text")):
            return [value]
        # Occasionally a model returns {"item_1": {...}, ...}.
        return [item for item in list(value.values())[:limit] if isinstance(item, dict)]
    return []


def _normalize_metadata(card: Any, pending: dict, raw: Any) -> dict:
    source_text = card._clean(pending.get("source_text"), 16000)
    analysis = card._clean(pending.get("analysis"), 12000)
    filename = card._safe_filename(pending.get("filename") or "medical_document")
    track = card._clean(pending.get("track"), 80)
    fallback = card._fallback_metadata(source_text, analysis, track, filename)
    data = raw if isinstance(raw, dict) else {}

    category = card._clean(data.get("category") or fallback.get("category") or "other", 30).lower()
    if category not in card.CATEGORY_LABELS:
        category = fallback.get("category") if fallback.get("category") in card.CATEGORY_LABELS else "other"

    result = {
        "title": card._clean(data.get("title") or fallback.get("title") or "Медицинский документ", 100),
        "document_date": card._clean(data.get("document_date") or fallback.get("document_date") or "", 20),
        "category": category,
        "specialty": card._clean(data.get("specialty") or fallback.get("specialty") or "", 80),
        "summary": card._clean(data.get("summary") or fallback.get("summary") or analysis, 1800),
        "organ_systems": [],
        "key_findings": _dict_items(data.get("key_findings"), 30),
        "measurements": _dict_items(data.get("measurements"), 100),
        "medications": _dict_items(data.get("medications"), 50),
        "follow_up": _dict_items(data.get("follow_up"), 20),
    }
    systems = data.get("organ_systems")
    if isinstance(systems, list):
        result["organ_systems"] = [card._clean(item, 80) for item in systems[:30] if card._clean(item, 80)]
    elif isinstance(systems, str):
        result["organ_systems"] = [card._clean(systems, 80)] if card._clean(systems, 80) else []
    return result


def _stable_fernet(card: Any, mod: Any):
    """Return one stable Fernet key shared by save and read operations."""
    from cryptography.fernet import Fernet

    configured = (os.environ.get("MEDICAL_CARD_ENCRYPTION_KEY") or "").strip()
    if configured:
        return Fernet(configured.encode("ascii"))

    root = card._storage_root(mod)
    key_path = root / ".medical_card_fernet.key"
    if key_path.exists():
        return Fernet(key_path.read_bytes().strip())

    key = Fernet.generate_key()
    try:
        fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, key)
        finally:
            os.close(fd)
    except FileExistsError:
        key = key_path.read_bytes().strip()
    return Fernet(key)


def _safe_insert_rows(card: Any, mod: Any, con: Any, document_id: str, profile_id: int, owner_id: int, meta: dict) -> None:
    created = card._now()

    for item in _dict_items(meta.get("key_findings"), 30):
        label = card._clean(item.get("label"), 500)
        if not label:
            continue
        with contextlib.suppress(Exception):
            con.execute(
                "INSERT INTO medical_findings(document_id, profile_id, label_enc, detail_enc, priority, created_ts) VALUES (?,?,?,?,?,?)",
                (document_id, profile_id, card._enc(mod, label), card._enc(mod, card._clean(item.get("detail"), 1500)), card._clean(item.get("priority") or "routine", 20), created),
            )

    for item in _dict_items(meta.get("measurements"), 100):
        name = card._clean(item.get("name"), 300)
        if not name:
            continue
        numeric = item.get("numeric_value")
        try:
            numeric = float(numeric) if numeric not in (None, "") else None
        except Exception:
            numeric = None
        with contextlib.suppress(Exception):
            con.execute(
                "INSERT INTO medical_measurements(document_id, profile_id, name_enc, value_text_enc, numeric_value, unit_enc, reference_enc, measured_date, created_ts) VALUES (?,?,?,?,?,?,?,?,?)",
                (document_id, profile_id, card._enc(mod, name), card._enc(mod, card._clean(item.get("value_text"), 300)), numeric, card._enc(mod, card._clean(item.get("unit"), 100)), card._enc(mod, card._clean(item.get("reference"), 300)), card._clean(meta.get("document_date"), 20), created),
            )

    for item in _dict_items(meta.get("medications"), 50):
        name = card._clean(item.get("name"), 300)
        if not name:
            continue
        with contextlib.suppress(Exception):
            con.execute(
                "INSERT INTO medical_medications(document_id, profile_id, name_enc, dosage_enc, schedule_enc, start_date, end_date, source_kind, status, created_ts) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (document_id, profile_id, card._enc(mod, name), card._enc(mod, card._clean(item.get("dosage"), 300)), card._enc(mod, card._clean(item.get("schedule"), 500)), card._clean(item.get("start_date"), 20), card._clean(item.get("end_date"), 20), card._clean(item.get("source_kind") or "document", 30), "recorded", created),
            )

    for item in _dict_items(meta.get("follow_up"), 20):
        title = card._clean(item.get("title"), 400)
        if not title:
            continue
        note = " — ".join(
            part for part in (
                card._clean(item.get("suggested_period"), 150),
                card._clean(item.get("reason"), 500),
            ) if part
        )
        with contextlib.suppress(Exception):
            con.execute(
                "INSERT INTO medical_reminders(owner_user_id, profile_id, document_id, due_ts, title_enc, note_enc, status, created_ts) VALUES (?,?,?,?,?,?,?,?)",
                (owner_id, profile_id, document_id, 0, card._enc(mod, title), card._enc(mod, note), "suggested", created),
            )


def _install_save_fix(card: Any) -> None:
    async def save_pending(mod: Any, update: Any, context: Any, profile_id: int | None = None):
        user = update.effective_user
        uid = int(user.id)
        pending = context.user_data.get("medcard_pending") or {}
        if not isinstance(pending, dict) or not pending:
            return False, "Нет нового медицинского разбора для сохранения.", ""
        if card._now() - int(pending.get("created_ts") or 0) > card.MAX_PENDING_SECONDS:
            context.user_data.pop("medcard_pending", None)
            return False, "Срок временного разбора истёк. Загрузите документ ещё раз.", ""
        if not card._eligible(mod, user):
            return False, "Медицинская карта доступна только в PRO и ULTIMATE.", ""
        if not card._has_consent(mod, uid):
            return False, "Сначала создайте медицинскую карту и подтвердите согласие на хранение.", ""

        pid = int(profile_id or card._default_profile_id(mod, uid))
        if not card._profile_owned(mod, uid, pid):
            return False, "Профиль не найден.", ""

        try:
            raw_meta = await card._classify(mod, pending)
        except Exception as exc:
            _log_exception(mod, "medical card classification failed; using fallback", exc)
            raw_meta = {}
        meta = _normalize_metadata(card, pending, raw_meta)

        document_id = str(uuid.uuid4())
        file_path = ""
        con = None
        stage = "подготовка данных"
        try:
            stage = "шифрование оригинала"
            file_path = card._write_encrypted_file(mod, uid, document_id, bytes(pending.get("file_bytes") or b""))
            stage = "открытие базы"
            now = card._now()
            con = card._connect(mod)
            con.execute("BEGIN IMMEDIATE")
            stage = "сохранение основной карточки"
            con.execute(
                "INSERT INTO medical_documents(id, owner_user_id, profile_id, category, specialty, title, document_date, source_type, original_filename, mime_type, encrypted_path, source_text_enc, analysis_enc, metadata_enc, created_ts, updated_ts, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    document_id, uid, pid, meta["category"], meta["specialty"], meta["title"], meta["document_date"],
                    card._clean(pending.get("source_type"), 40), card._safe_filename(pending.get("filename") or "medical_document"),
                    card._clean(pending.get("mime_type") or "application/octet-stream", 100), file_path,
                    card._enc(mod, pending.get("source_text") or ""), card._enc(mod, pending.get("analysis") or ""),
                    card._enc(mod, json.dumps(meta, ensure_ascii=False)), now, now, "active",
                ),
            )
            stage = "сохранение показателей"
            _safe_insert_rows(card, mod, con, document_id, pid, uid, meta)
            con.commit()
            con.close()
            con = None
        except Exception as exc:
            if con is not None:
                with contextlib.suppress(Exception):
                    con.rollback()
                with contextlib.suppress(Exception):
                    con.close()
            if file_path:
                with contextlib.suppress(Exception):
                    Path(file_path).unlink()
            error_id = hashlib.sha256(f"{stage}|{type(exc).__name__}|{exc}".encode("utf-8", errors="ignore")).hexdigest()[:8]
            _log_exception(mod, f"medical card save failed at {stage}; error_id={error_id}", exc)
            return False, f"Не удалось сохранить документ на этапе «{stage}». Код ошибки: {error_id}. Повторите сохранение; сам разбор пока не удалён.", ""

        context.user_data.pop("medcard_pending", None)
        card._audit(mod, uid, "document_save", "document", document_id)
        label = card.CATEGORY_LABELS.get(meta["category"], card.CATEGORY_LABELS.get("other", "Документ"))
        profile_name = card._profile_name(mod, uid, pid)
        return True, f"✅ Сохранено в «{profile_name}» → {label}.\nДокумент: {meta['title']}", document_id

    card._save_pending = save_pending


def _install_medical_routing(mod: Any) -> None:
    original = getattr(mod, "_should_route_medical", None)
    if not callable(original) or getattr(original, "_medical_v110_wrapped", False):
        return

    conflicting_flags = (
        "awaiting_photo_for", "photo_flow", "awaiting_avatar_photo", "awaiting_ai_selfie_photo",
        "awaiting_vocal_clip_photo", "awaiting_photo_clip_photo", "retouch_wait_text",
        "awaiting_reels_material", "awaiting_film_material",
    )

    def should_route(context: Any, user_id: int, caption_or_text: str = "", filename: str = "") -> bool:
        with contextlib.suppress(Exception):
            if original(context, user_id, caption_or_text, filename):
                return True
        if context and any(context.user_data.get(key) for key in conflicting_flags):
            return False
        mode = ""
        track = ""
        with contextlib.suppress(Exception):
            mode = str(mod._mode_get(int(user_id)) or "")
        with contextlib.suppress(Exception):
            track = str(mod._mode_track_get(int(user_id)) or "")
        normalized = mode.strip().lower().replace("ё", "е")
        return normalized in {"медицина", "medicine", "medical"} or track.startswith("med_")

    should_route._medical_v110_wrapped = True
    mod._should_route_medical = should_route


def _install_clinical_prompt_fix(med108: Any) -> None:
    if getattr(med108, "_MEDICAL_V110_PROMPTS", False):
        return

    original_extract = med108._extraction_prompt
    original_analysis = med108._analysis_prompt
    original_review = med108._review_prompt

    def extraction_prompt(track: str, goal: str | None) -> str:
        return original_extract(track, goal) + """

ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА ТОЧНОСТИ
• Если на одном листе описаны разные области (например, органы малого таза и щитовидная железа), создай отдельные подблоки и не смешивай их размеры.
• Для каждого органа сохрани сторону, три размера, единицы, структуру, кровоток, категорию и динамику дословно.
• Перед ответом повторно сравни все числа с изображением. Не заменяй 28,6 на 34, не сокращай 15,8 до 15 и не меняй правую сторону на левую.
• Формулировки «диффузно неоднородная», «неоднородное», «анэхогенное», «гиперэхогенные включения» не упрощай до противоположного значения.
"""

    def analysis_prompt(source_text: str, track: str, goal: str | None, source_type: str) -> str:
        return original_analysis(source_text, track, goal, source_type) + """

ОБЯЗАТЕЛЬНЫЙ КЛИНИЧЕСКИЙ КОНТРОЛЬ
• Не используй пугающую универсальную фразу «образование может быть злокачественным». Объясняй только реальную категорию риска и ограничения документа.
• TI-RADS 2 — категория низкой подозрительности. Формулировка «TI-RADS 3–4» неоднозначна: требуется одна категория и указание системы ACR/EU/иной. Это не диагноз рака.
• Для узлов щитовидной железы не называй гормональную терапию стандартным способом лечения. Не предлагай операцию без цитологии, компрессионных симптомов, функциональной активности, значимого роста или иной подтверждённой причины.
• Порог пункции называй только вместе с системой. Узел около 15–16 мм может находиться у порога пункции для некоторых категорий 4, но при категории 3 тактика часто иная; сначала нужна экспертная классификация.
• Увеличение узла само по себе не является экстренным красным флагом. Срочность повышают затруднение дыхания/глотания, быстро нарастающая припухлость, стойкая осиплость, тяжёлое кровотечение, обморок или резкая сильная боль.
• Аденомиоз — доброкачественное состояние; лечение зависит прежде всего от боли, объёма кровотечений, анемии и репродуктивных планов.
• Простое аваскулярное параовариальное образование около 4 мм, особенно уменьшающееся, обычно не требует операции и описывается как малозначимая находка для планового наблюдения.
• Не назначай биопсию «в ближайшие дни» без обоснования. Разделяй: плановая консультация, экспертное УЗИ и решение о пункции после точной категории.
• Если источник содержит два разных исследования, дай отдельный итог по каждому и единый приоритет в начале.
"""

    def review_prompt(source_text: str, draft: str) -> str:
        return original_review(source_text, draft) + """

ФИНАЛЬНЫЙ АУДИТ
1. Сверь каждое число, сторону и единицу с источником; исправь любые перестановки размеров.
2. Удали утверждения о злокачественности, лечении гормонами или операции, если они не следуют из документа.
3. Удали ложную срочность: плановый эндокринолог/экспертное УЗИ не равны экстренному обращению.
4. Для неоднозначного TI-RADS 3–4 обязательно объясни необходимость одной категории и названия системы.
5. Не смешивай гинекологические и тиреоидные находки в одном абзаце.
"""

    med108._extraction_prompt = extraction_prompt
    med108._analysis_prompt = analysis_prompt
    med108._review_prompt = review_prompt
    med108._MEDICAL_V110_PROMPTS = True


def patch_runtime(mod: Any) -> bool:
    global _INSTALLED
    if getattr(mod, _PATCH_FLAG, False):
        mod.PATCH_VERSION = VERSION
        return True
    try:
        import medical_card_v109_patch as card
        import medical_v108_patch as med108
    except Exception:
        return False
    if not getattr(mod, card.PATCH_FLAG, False):
        return False

    card._fernet = lambda runtime_mod: _stable_fernet(card, runtime_mod)
    _install_save_fix(card)
    _install_medical_routing(mod)
    _install_clinical_prompt_fix(med108)

    card.VERSION = VERSION
    med108.VERSION = VERSION
    mod.MEDICAL_CARD_VERSION = VERSION
    mod.MEDICAL_PATCH_VERSION = VERSION
    mod.PATCH_VERSION = VERSION
    setattr(mod, _PATCH_FLAG, True)
    _INSTALLED = True
    return True


def install_async() -> None:
    def worker() -> None:
        for _ in range(9000):
            for name in ("__main__", "main"):
                mod = sys.modules.get(name)
                if mod is None:
                    continue
                try:
                    if patch_runtime(mod):
                        return
                except Exception as exc:
                    _log_exception(mod, "medical v110 install failed", exc)
            time.sleep(0.02)

    threading.Thread(target=worker, daemon=True, name="medical-card-v110-patch").start()


__all__ = ["VERSION", "patch_runtime", "install_async"]
