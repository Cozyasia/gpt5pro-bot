# -*- coding: utf-8 -*-
"""v114 reliability overlay for the existing modular medical engine.

This file intentionally patches the existing v111-named modules at import time so
main.py remains untouched and Render receives one small, reversible integration.
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
from typing import Any

import medical_engine_v111 as engine
import medical_v111_client as client
import medical_v111_reasoning as reasoning
import medical_v111_runtime as runtime
from medical_v111_prompts import (
    AUDIT_SCHEMA,
    AUDIT_SYSTEM,
    EXTRACT_SCHEMA,
    REASON_SYSTEM,
)

VERSION = "v114-balanced-openai-medical-structured-2026-07-18"
_INSTALLED = False


def _structured_request_variants(
    model: str,
    system: str,
    user_content: Any,
    effort: str,
    max_tokens: int,
    json_mode: bool,
) -> list[dict[str, Any]]:
    base: dict[str, Any] = {
        "model": model,
        "instructions": system + ("\nReturn exactly one valid JSON object." if json_mode else ""),
        "input": client._responses_input(user_content),
        "max_output_tokens": max_tokens,
        "store": False,
    }
    if effort != "none" and (model.startswith("gpt-5") or model.startswith("o")):
        base["reasoning"] = {"effort": effort}

    variants: list[dict[str, Any]] = []
    if json_mode:
        is_extract = "medical document extraction" in system.lower()
        schema = EXTRACT_SCHEMA if is_extract else AUDIT_SCHEMA
        name = "medical_extract_v114" if is_extract else "medical_audit_v114"
        strict = dict(base)
        strict["text"] = {
            "format": {
                "type": "json_schema",
                "name": name,
                "description": "Strict source-grounded medical structured output",
                "strict": True,
                "schema": schema,
            }
        }
        variants.append(strict)
        if "reasoning" in strict:
            no_reasoning = dict(strict)
            no_reasoning.pop("reasoning", None)
            variants.append(no_reasoning)

        compatibility = dict(base)
        compatibility.pop("reasoning", None)
        compatibility["text"] = {"format": {"type": "json_object"}}
        variants.append(compatibility)
    else:
        variants.append(dict(base))
        if "reasoning" in base:
            no_reasoning = dict(base)
            no_reasoning.pop("reasoning", None)
            variants.append(no_reasoning)

    unique: list[dict[str, Any]] = []
    seen = set()
    for variant in variants:
        marker = json.dumps(variant, ensure_ascii=False, sort_keys=True)
        if marker not in seen:
            seen.add(marker)
            unique.append(variant)
    return unique


def _strings(value: Any, limit: int = 50, item_limit: int = 800) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [
        client.clean(item, item_limit)
        for item in value[:limit]
        if client.clean(item, item_limit)
    ]


def _derived_confidence(result: dict) -> float:
    score = 0.35
    if result.get("document_title"):
        score += 0.08
    if result.get("document_date"):
        score += 0.04
    if result.get("findings"):
        score += min(0.25, 0.05 * len(result["findings"]))
    if result.get("impression"):
        score += 0.10
    if result.get("body_regions"):
        score += 0.05
    quality = result.get("image_quality")
    if quality == "good":
        score += 0.08
    elif quality == "poor":
        score -= 0.20
    score -= min(0.25, 0.05 * len(result.get("unreadable_fragments") or []))
    return max(0.05, min(0.98, score))


def _normalize_extraction_factory(original):
    def normalize(data: dict) -> dict:
        result = original(data)
        if not isinstance(result, dict):
            result = {}

        for key in (
            "specialties", "body_regions", "impression",
            "recommendations_in_source", "unreadable_fragments",
            "contradictions", "source_consistency_notes",
            "raw_image_limitations",
        ):
            result[key] = _strings(result.get(key))

        context = result.get("patient_context")
        if not isinstance(context, dict):
            context = {}
        result["patient_context"] = {
            "age": client.clean(context.get("age"), 60),
            "sex": client.clean(context.get("sex"), 60),
            "cycle_day": client.clean(context.get("cycle_day"), 60),
            "pregnancy": client.clean(context.get("pregnancy"), 120),
            "symptoms": _strings(context.get("symptoms"), 20, 300),
            "other": _strings(context.get("other"), 20, 300),
        }

        try:
            supplied = float(result.get("confidence"))
        except Exception:
            supplied = 0.0
        if supplied <= 0 and (result.get("findings") or result.get("impression")):
            result["confidence"] = _derived_confidence(result)
        else:
            result["confidence"] = max(0.0, min(1.0, supplied))

        cycle_day = result["patient_context"].get("cycle_day", "")
        if cycle_day:
            result["source_consistency_notes"].append(
                f"День менструального цикла указан в источнике: {cycle_day}; не считать его отсутствующим."
            )

        for finding in result.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            text = " ".join([
                client.clean(finding.get("section"), 200),
                client.clean(finding.get("organ_or_test"), 200),
                client.clean(finding.get("finding"), 800),
            ]).lower().replace("ё", "е")
            if "м-эхо" in text or "м эхо" in text:
                result["source_consistency_notes"].append(
                    "М-эхо относится к эндометрию/эндометриальному эху, не к толщине миометрия."
                )
                break

        result["source_consistency_notes"] = list(
            dict.fromkeys(result["source_consistency_notes"])
        )[:50]
        return result

    return normalize


def _reason_prompt(extraction: dict, goal: str, history: str, guidelines: str) -> str:
    context = extraction.get("patient_context") or {}
    guards = extraction.get("source_consistency_notes") or []
    prompt = (
        f"USER GOAL:\n{goal or 'Подробно объяснить документ, риски, варианты тактики и действия.'}\n\n"
        f"STRUCTURED SOURCE:\n{json.dumps(extraction, ensure_ascii=False)}\n\n"
        "MANDATORY SOURCE CHECKS:\n"
        f"• cycle_day={client.clean(context.get('cycle_day'), 60) or 'not stated'}\n"
        f"• source consistency notes={json.dumps(guards, ensure_ascii=False)}\n"
        "• Do not present image_quality/confidence/model routing as wording from the report.\n"
        "• Compare every measurement, side, date, negation and classification with STRUCTURED SOURCE."
    )
    if history:
        prompt += "\n\n" + history
    if guidelines:
        prompt += "\n\nAUTHORITATIVE GUIDELINE SNIPPETS:\n" + guidelines
    return prompt


async def _reason_and_audit(
    mod: Any,
    run: dict,
    extraction: dict,
    goal: str,
    user: Any,
    plan: dict,
) -> tuple[str, dict]:
    tier = client.user_tier(mod, user)
    guidelines = await reasoning.guideline_context(mod, extraction, tier)
    history = reasoning.history_context(mod, user, extraction)

    draft, reasoning_model = await client.call_model(
        mod,
        run,
        "reason",
        client.fallbacks(plan["reason"], "reason"),
        REASON_SYSTEM,
        _reason_prompt(extraction, goal, history, guidelines),
        plan["effort"],
        plan["max_output"],
        False,
    )

    audit_prompt = (
        f"STRUCTURED SOURCE:\n{json.dumps(extraction, ensure_ascii=False)}\n\n"
        f"DRAFT:\n{draft[:30000]}\n\n"
        "FINAL CHECKLIST:\n"
        "1. All measurements, dates, sides, classifications, cycle day and negations match the source.\n"
        "2. М-эхо is not called myometrial thickness.\n"
        "3. A present cycle day is not listed as missing.\n"
        "4. Internal metadata is not presented as report wording.\n"
        "5. Ambiguous TI-RADS 3–4 remains ambiguous and biopsy is conditional.\n"
        "6. The answer explains significance, uncertainty, treatment categories, timing and red flags."
    )
    if guidelines:
        audit_prompt += "\n\nGUIDELINE CONTEXT:\n" + guidelines

    audit_raw, audit_model = await client.call_model(
        mod,
        run,
        "audit",
        client.fallbacks(plan["audit"], "audit"),
        AUDIT_SYSTEM,
        audit_prompt,
        "medium",
        client.int_env("MEDICAL_AUDIT_MAX_OUTPUT", 5600, 2200, 9000),
        True,
    )
    audit = client.parse_json(audit_raw)
    corrected = client.plain(audit.get("corrected_answer"))
    draft_plain = client.plain(draft)
    answer = (
        corrected
        if len(corrected) >= max(700, int(len(draft_plain) * 0.50))
        else draft_plain
    )
    return answer, {
        "reasoning_model": reasoning_model,
        "audit_model": audit_model,
        "guideline_search_used": bool(guidelines),
        "history_used": bool(history),
        "audit_pass": bool(audit.get("pass")),
        "audit_risk_level": client.clean(audit.get("risk_level"), 30),
        "audit_issues": audit.get("issues", []) if isinstance(audit.get("issues"), list) else [],
        "factual_corrections": (
            audit.get("factual_corrections", [])
            if isinstance(audit.get("factual_corrections"), list)
            else []
        ),
    }


def _source_warning_needed(extraction: dict) -> bool:
    try:
        confidence = float(extraction.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    return (
        extraction.get("image_quality") == "poor"
        or confidence < 0.35
        or len(extraction.get("unreadable_fragments") or []) >= 3
    )


async def _analyze(
    mod: Any,
    update: Any,
    context: Any,
    source: Any,
    goal: str | None,
    is_image: bool,
) -> None:
    user = update.effective_user
    tier = client.user_tier(mod, user)
    plan = client.model_plan(tier)
    track = str(mod._mode_track_get(user.id) or "")
    goal_text = client.clean(goal, 1500)
    run = {"calls": [], "fallbacks": [], "transports": []}
    stage = "extract"

    await update.effective_message.reply_text(
        "🩺 Сначала точно считываю медицинский документ и отделяю факты от интерпретации. "
        "Затем проверю клинический смысл, срочность, возможную дальнейшую тактику и каждое число."
    )

    try:
        if is_image:
            mime = mod.sniff_image_mime(source)
            extraction = await client.extract_image(
                mod, run, source, mime, goal_text, track, plan["extract"]
            )
        else:
            mime = "text/plain"
            extraction = await client.extract_text(
                mod, run, client.clean(source, 60000), goal_text, track, plan["extract"]
            )

        if _source_warning_needed(extraction):
            await update.effective_message.reply_text(
                "⚠️ Документ распознан, но отдельные мелкие или нечёткие фрагменты требуют "
                "проверки по оригиналу. Ограничения будут явно отмечены в ответе."
            )
        else:
            await update.effective_message.reply_text(
                "✅ Факты структурированы. Формирую содержательный медицинский разбор и "
                "независимо проверяю числа, стороны, термины и рекомендации…"
            )

        stage = "reason"
        answer, engine_meta = await _reason_and_audit(
            mod, run, extraction, goal_text, user, plan
        )
        stage = "audit"

        if run.get("fallbacks"):
            client.log(
                mod, "warning",
                "medical official fallback route: %s",
                json.dumps(run["fallbacks"], ensure_ascii=False),
            )
            if client.flag("MEDICAL_SHOW_TECHNICAL_ROUTE", False):
                await update.effective_message.reply_text(
                    "ℹ️ Анализ завершён официальной резервной моделью. "
                    "Технические детали доступны в /diag_medical."
                )

    except client.MedicalAPIError as exc:
        error_id = hashlib.sha256(
            f"{exc.category}|{exc.status}|{exc}".encode()
        ).hexdigest()[:8]
        client.log(
            mod, "error",
            "medical v114 failed %s at %s [%s]: %s\n%s",
            error_id, stage, exc.category, exc, traceback.format_exc(),
        )
        runtime._capture(context)
        await update.effective_message.reply_text(
            runtime._public_api_error(exc, stage, error_id)
        )
        keyboard = None
        with contextlib.suppress(Exception):
            keyboard = mod.medicine_kb()
        if keyboard is not None:
            await update.effective_message.reply_text(
                "Документ не сохранён и клинический ответ не сформирован, потому что "
                "официальный API не завершил полный анализ.",
                reply_markup=keyboard,
            )
        return
    except Exception as exc:
        error_id = hashlib.sha256(
            f"{type(exc).__name__}|{exc}".encode()
        ).hexdigest()[:8]
        client.log(
            mod, "error",
            "medical v114 unexpected failure %s at %s: %r\n%s",
            error_id, stage, exc, traceback.format_exc(),
        )
        runtime._capture(context)
        await update.effective_message.reply_text(
            f"⚠️ Внутренняя ошибка этапа {runtime._stage_label(stage)}. "
            f"Старый OpenRouter-анализатор не использован. Код диагностики: {error_id}."
        )
        return

    engine_meta["calls"] = run["calls"]
    engine_meta["fallbacks"] = run["fallbacks"]
    engine_meta["transports"] = run["transports"]
    engine_meta["estimated_cost_usd"] = round(
        sum(item.get("cost_usd", 0) for item in run["calls"]),
        6,
    )
    await runtime._send_answer(mod, update, context, answer)

    capture = runtime._capture(context)
    if is_image:
        raw = source
        filename = capture.get("filename") or "medical_photo.jpg"
        stored_mime = capture.get("mime_type") or mime
        source_type = "image"
    else:
        raw = bytes(
            capture.get("file_bytes")
            or client.clean(source).encode("utf-8")
        )
        filename = capture.get("filename") or "medical_document.txt"
        stored_mime = capture.get("mime_type") or "text/plain"
        source_type = "text"

    runtime._set_pending(
        context, track, goal_text, source_type, filename, stored_mime,
        raw, extraction, answer, engine_meta,
    )
    await runtime._offer_save(mod, update, context)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    client._request_variants = _structured_request_variants
    client.normalize_extraction = _normalize_extraction_factory(
        client.normalize_extraction
    )
    reasoning.reason_and_audit = _reason_and_audit
    runtime.reason_and_audit = _reason_and_audit
    runtime.analyze = _analyze

    engine.VERSION = VERSION
    runtime.VERSION = VERSION
    reasoning.VERSION = VERSION
    client.VERSION = VERSION
    engine.analyze = _analyze

    original_patch_runtime = engine.patch_runtime
    if not getattr(original_patch_runtime, "_v114_wrapped", False):
        def patch_runtime(mod: Any) -> bool:
            ok = original_patch_runtime(mod)
            if ok:
                mod.PATCH_VERSION = VERSION
                mod.MEDICAL_ENGINE_VERSION = VERSION
                mod.MEDICAL_PATCH_VERSION = VERSION
                mod.MEDICAL_CARD_VERSION = VERSION
                mod._medical_capability_text = lambda: (
                    "🩺 Универсальный медицинский анализ: строгое структурированное чтение, "
                    "клинический разбор и независимая проверка фактов. Бот автоматически "
                    "определяет анализы, УЗИ, КТ, МРТ, рентген, ЭКГ, гистологию, выписки "
                    "и назначения; для PRO/ULTIMATE может учитывать медицинскую карту "
                    "и актуальные рекомендации. Это справочный инструмент, не диагноз."
                )
                mod._medical_menu_text = lambda track="": (
                    "🩺 Медицина — углублённый анализ\n\n"
                    "Загрузите PDF/DOCX/TXT или чёткое фото. Бот сам определит тип документа, "
                    "проверит числа и стороны, объяснит значение находок, срочность, "
                    "варианты дальнейшей тактики и вопросы врачу."
                )
            return ok

        patch_runtime._v114_wrapped = True
        engine.patch_runtime = patch_runtime

    _INSTALLED = True


def install_async() -> None:
    install()

    def worker() -> None:
        for _ in range(12000):
            for name in ("__main__", "main"):
                mod = sys.modules.get(name)
                if mod is None:
                    continue
                with contextlib.suppress(Exception):
                    mod.PATCH_VERSION = VERSION
                    mod.MEDICAL_ENGINE_VERSION = VERSION
                    mod.MEDICAL_PATCH_VERSION = VERSION
                    mod.MEDICAL_CARD_VERSION = VERSION
                    if getattr(mod, engine.PATCH_FLAG, False):
                        return
            time.sleep(0.02)

    threading.Thread(
        target=worker,
        daemon=True,
        name="medical-v114-overlay",
    ).start()


__all__ = ["VERSION", "install", "install_async"]
