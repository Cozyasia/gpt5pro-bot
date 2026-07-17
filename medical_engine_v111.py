# -*- coding: utf-8 -*-
"""Universal GPT-5.6 medical engine bootstrap v111."""
from __future__ import annotations

import contextlib
import sys
import threading
import time
from typing import Any

from medical_v111_client import api_key, base_url, flag, log, model_plan, user_tier
from medical_v111_runtime import analyze

VERSION = "v111-universal-medical-gpt56-engine-2026-07-18"
PATCH_FLAG = "_MEDICAL_ENGINE_V111_PATCHED"


def _install_card_classifier() -> None:
    try:
        import medical_card_v109_patch as card
    except Exception:
        return
    original = card._classify
    if getattr(original, "_medical_v111_wrapped", False):
        return

    async def classify(runtime_mod: Any, pending: dict):
        hint = pending.get("metadata_hint") if isinstance(pending, dict) else None
        if isinstance(hint, dict) and hint.get("title") and hint.get("category"):
            return hint
        return await original(runtime_mod, pending)

    classify._medical_v111_wrapped = True
    card._classify = classify


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BOT_TOKEN"):
            return module
    return None


async def _diag_medical(update: Any, context: Any) -> None:
    mod = _runtime_module()
    if mod is None:
        return
    tier = user_tier(mod, update.effective_user)
    plan = model_plan(tier)
    tavily = str(getattr(mod, "TAVILY_API_KEY", "") or "").strip()
    await update.effective_message.reply_text(
        "🩺 Medical Engine diagnostic\n"
        f"version={VERSION}\n"
        f"tier={tier}\n"
        f"extract_model={plan['extract']}\n"
        f"reasoning_model={plan['reason']}\n"
        f"audit_model={plan['audit']}\n"
        f"reasoning_effort={plan['effort']}\n"
        f"medical_openai_key={'on' if api_key(mod) else 'off'}\n"
        f"medical_base_url={base_url()}\n"
        f"guideline_search={'on' if flag('MEDICAL_GUIDELINE_SEARCH', True) else 'off'}\n"
        f"tavily_key={'on' if tavily else 'off'}\n"
        f"medical_card_version={getattr(mod, 'MEDICAL_CARD_VERSION', '—')}"
    )


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception:
        return
    if getattr(ApplicationBuilder, "_medical_v111_hooked", False):
        return
    original_build = ApplicationBuilder.build

    def build(self, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, "_medical_v111_handlers", False):
            app.add_handler(CommandHandler("diag_medical", _diag_medical), group=-3)
            setattr(app, "_medical_v111_handlers", True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, "_medical_v111_hooked", True)


def patch_runtime(mod: Any) -> bool:
    if getattr(mod, PATCH_FLAG, False):
        mod.PATCH_VERSION = VERSION
        return True
    required = ("_medical_analyze_text", "_medical_analyze_image", "_mode_track_get", "sniff_image_mime")
    if not all(hasattr(mod, name) for name in required):
        return False
    if not str(getattr(mod, "MEDICAL_CARD_VERSION", "")).startswith("v110"):
        return False

    async def analyze_text(update, context, value, goal=None):
        await analyze(mod, update, context, value, goal, False)

    async def analyze_image(update, context, value, goal=None):
        await analyze(mod, update, context, value, goal, True)

    mod._medical_analyze_text = analyze_text
    mod._medical_analyze_image = analyze_image
    mod._medical_capability_text = lambda: (
        "🩺 Универсальный медицинский анализ GPT-5.6: автоматическое определение анализов, "
        "УЗИ, КТ, МРТ, рентгена, ЭКГ, гистологии, выписок и назначений; точное извлечение; "
        "клинический разбор; независимый аудит; актуальные источники для PRO/ULTIMATE; "
        "сравнение с медицинской картой. Это справочный инструмент, не диагноз."
    )
    mod._medical_menu_text = lambda track="": (
        "🩺 Медицина — универсальный анализ GPT-5.6\n\n"
        "Загрузите PDF/DOCX/TXT или чёткое фото. Бот сам определит тип документа и область "
        "исследования. Этапы: структурированное извлечение → клиническое рассуждение → "
        "независимый аудит → сохранение в медицинскую карту."
    )
    _install_card_classifier()

    for name in ("medical_v108_patch", "medical_card_v109_patch", "medical_card_v110_patch"):
        with contextlib.suppress(Exception):
            sys.modules[name].VERSION = VERSION

    mod.MEDICAL_ENGINE_VERSION = VERSION
    mod.MEDICAL_PATCH_VERSION = VERSION
    mod.MEDICAL_CARD_VERSION = VERSION
    mod.PATCH_VERSION = VERSION
    setattr(mod, PATCH_FLAG, True)
    log(mod, "info", "Universal medical engine installed: %s", VERSION)
    return True


def install_async() -> None:
    def worker() -> None:
        for _ in range(12000):
            for name in ("__main__", "main"):
                mod = sys.modules.get(name)
                if mod is None:
                    continue
                with contextlib.suppress(Exception):
                    if patch_runtime(mod):
                        return
            time.sleep(0.02)

    threading.Thread(target=worker, daemon=True, name="medical-v111").start()


__all__ = ["VERSION", "install_builder_hook", "patch_runtime", "install_async"]
