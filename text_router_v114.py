# -*- coding: utf-8 -*-
"""Balanced official OpenAI router for ordinary Neyro-Bot text and vision requests."""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import sys
import threading
import time
from typing import Any

import httpx

VERSION = "v114-balanced-openai-medical-structured-2026-07-18"
PATCH_FLAG = "_GENERAL_TEXT_ROUTER_V114_PATCHED"

PRICES = {
    "gpt-5.2": (1.75, 14.00),
    "gpt-5.1": (1.25, 10.00),
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4o-mini": (0.15, 0.60),
}

_MODEL_CACHE: dict[str, Any] = {"at": 0.0, "models": [], "error": ""}
_LAST_ROUTE: dict[str, Any] = {}

_COMPLEX_RE = re.compile(
    r"(проанализ|глубок|подробн|сравни|стратег|бизнес.?план|финансов|юридичес|"
    r"договор|архитектур|исследован|отч[её]т|аудит|код|программ|алгоритм|"
    r"пошагов|презентац|маркетингов|рассчита|обоснуй|критическ)",
    re.I,
)


def _flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() not in {"0", "false", "no", "off"}


def _clean(value: Any, limit: int = 60000) -> str:
    text = str(value or "").replace("\x00", " ").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text[:limit]


def _log(mod: Any, level: str, message: str, *args: Any) -> None:
    logger = getattr(mod, "log", None)
    if logger:
        with contextlib.suppress(Exception):
            getattr(logger, level)(message, *args)
            return


def _key(mod: Any) -> str:
    return (
        os.environ.get("GENERAL_OPENAI_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
        or str(getattr(mod, "OPENAI_API_KEY", "") or "").strip()
    )


def _key_source(mod: Any) -> str:
    if os.environ.get("GENERAL_OPENAI_API_KEY", "").strip():
        return "GENERAL_OPENAI_API_KEY"
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return "OPENAI_API_KEY"
    if str(getattr(mod, "OPENAI_API_KEY", "") or "").strip():
        return "runtime OPENAI_API_KEY"
    return "missing"


def _fingerprint(mod: Any) -> str:
    value = _key(mod)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10] if value else "—"


def _base_url() -> str:
    value = (
        os.environ.get("GENERAL_OPENAI_BASE_URL", "")
        or "https://api.openai.com/v1"
    ).strip()
    if not value or "openrouter.ai" in value.lower():
        value = "https://api.openai.com/v1"
    return value.rstrip("/")


def _headers(mod: Any) -> dict[str, str]:
    key = _key(mod)
    if not key:
        raise RuntimeError("Official OpenAI API key is missing")
    if key.startswith("sk-or-"):
        raise RuntimeError("OpenRouter key cannot be used for the official general route")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _extract_text(data: dict) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"}:
                value = content.get("text")
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
    return "\n".join(parts).strip()


def _tier(mod: Any, user_id: int | None) -> str:
    if not user_id:
        return "free"
    with contextlib.suppress(Exception):
        if mod.is_unlimited(int(user_id), ""):
            return "ultimate"
    with contextlib.suppress(Exception):
        value = str(mod.get_subscription_tier(int(user_id)) or "free").lower()
        if value in {"free", "start", "pro", "ultimate"}:
            return value
    return "free"


def _is_complex(text: str, tier: str) -> bool:
    if tier not in {"pro", "ultimate"}:
        return False
    min_chars = max(500, min(6000, int(os.environ.get("GENERAL_COMPLEX_MIN_CHARS", "1100") or 1100)))
    return len(text) >= min_chars or bool(_COMPLEX_RE.search(text))


def _model_plan(tier: str, text: str) -> tuple[str, str, int, bool]:
    complex_request = _is_complex(text, tier)
    if tier == "ultimate":
        normal = os.environ.get("GENERAL_MODEL_ULTIMATE", "gpt-5-mini").strip() or "gpt-5-mini"
        complex_model = os.environ.get("GENERAL_MODEL_COMPLEX_ULTIMATE", "gpt-5").strip() or "gpt-5"
        effort = os.environ.get("GENERAL_REASONING_EFFORT_ULTIMATE", "medium").strip().lower()
        return (complex_model if complex_request else normal, effort, 3600, complex_request)
    if tier == "pro":
        normal = os.environ.get("GENERAL_MODEL_PRO", "gpt-5-mini").strip() or "gpt-5-mini"
        complex_model = os.environ.get("GENERAL_MODEL_COMPLEX_PRO", "gpt-5").strip() or "gpt-5"
        effort = os.environ.get("GENERAL_REASONING_EFFORT_PRO", "low").strip().lower()
        return (complex_model if complex_request else normal, effort, 3000, complex_request)
    model = os.environ.get("GENERAL_MODEL_BASIC", "gpt-5-mini").strip() or "gpt-5-mini"
    effort = os.environ.get("GENERAL_REASONING_EFFORT_BASIC", "low").strip().lower()
    return model, effort, 2200, False


async def _available_models(mod: Any, force: bool = False) -> list[str]:
    now = time.monotonic()
    if not force and _MODEL_CACHE["models"] and now - float(_MODEL_CACHE["at"]) < 900:
        return list(_MODEL_CACHE["models"])
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(_base_url() + "/models", headers=_headers(mod))
        response.raise_for_status()
        models = sorted({
            str(item.get("id"))
            for item in (response.json().get("data") or [])
            if isinstance(item, dict) and item.get("id")
        })
        _MODEL_CACHE.update({"at": now, "models": models, "error": ""})
        return models
    except Exception as exc:
        _MODEL_CACHE.update({"at": now, "models": [], "error": _clean(exc, 500)})
        return []


async def _resolve_models(mod: Any, primary: str) -> list[str]:
    candidates = [primary, "gpt-5-mini", "gpt-5", "gpt-4.1-mini"]
    candidates = list(dict.fromkeys(model for model in candidates if model))
    available = await _available_models(mod)
    if available:
        resolved = [model for model in candidates if model in available]
        if resolved:
            return resolved
        discovered = [
            model for model in available
            if re.match(r"^(gpt-5|gpt-4\.1|gpt-4o)(?:$|-)", model)
            and all(token not in model for token in ("audio", "realtime", "transcribe", "tts"))
        ]
        if discovered:
            return discovered[:4]
    return candidates


def _usage_cost(model: str, data: dict) -> tuple[int, int, float]:
    usage = data.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    in_price, out_price = PRICES.get(model, (0.0, 0.0))
    cost = (input_tokens * in_price + output_tokens * out_price) / 1_000_000
    return input_tokens, output_tokens, round(cost, 6)


async def _responses_call(
    mod: Any,
    instructions: str,
    input_messages: list[dict[str, Any]],
    primary_model: str,
    effort: str,
    max_output_tokens: int,
) -> str:
    global _LAST_ROUTE
    timeout = httpx.Timeout(connect=20, read=150, write=60, pool=20)
    last_error: Exception | None = None
    resolved = await _resolve_models(mod, primary_model)

    for model in resolved:
        variants: list[tuple[str, dict[str, Any]]] = []
        body: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": input_messages,
            "max_output_tokens": max_output_tokens,
            "store": False,
        }
        if effort in {"low", "medium", "high"} and model.startswith("gpt-5"):
            body["reasoning"] = {"effort": effort}
        variants.append(("reasoning" if "reasoning" in body else "standard", body))
        if "reasoning" in body:
            simpler = dict(body)
            simpler.pop("reasoning", None)
            variants.append(("standard", simpler))

        for variant_index, (variant_name, payload) in enumerate(variants):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        _base_url() + "/responses",
                        headers=_headers(mod),
                        json=payload,
                    )
                request_id = response.headers.get("x-request-id", "")
                if response.status_code >= 400:
                    _log(
                        mod, "warning",
                        "general Responses API HTTP %s model=%s variant=%s request_id=%s: %s",
                        response.status_code, model, variant_name, request_id, response.text[:700],
                    )
                    if response.status_code == 400 and variant_index < len(variants) - 1:
                        continue
                    response.raise_for_status()

                data = response.json()
                text = _extract_text(data)
                if not text:
                    raise RuntimeError(
                        f"empty response status={data.get('status')} "
                        f"details={data.get('incomplete_details')}"
                    )
                input_tokens, output_tokens, cost = _usage_cost(model, data)
                _LAST_ROUTE = {
                    "model": model,
                    "requested": primary_model,
                    "variant": variant_name,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "estimated_cost_usd": cost,
                    "request_id": request_id,
                    "at": int(time.time()),
                }
                _log(
                    mod, "info",
                    "general official route model=%s requested=%s in=%s out=%s cost=$%.6f",
                    model, primary_model, input_tokens, output_tokens, cost,
                )
                return text.strip()
            except Exception as exc:
                last_error = exc
                _log(
                    mod, "warning",
                    "general official route failed model=%s variant=%s: %r",
                    model, variant_name, exc,
                )
                await __import__("asyncio").sleep(0.5)

    raise RuntimeError(f"all official general models failed: {last_error!r}")


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


async def _diag_text(update: Any, context: Any) -> None:
    mod = _runtime_module()
    if mod is None:
        return
    user_id = int(getattr(update.effective_user, "id", 0) or 0)
    tier = _tier(mod, user_id)
    model, effort, max_output, _ = _model_plan(tier, "")
    models = await _available_models(mod, force=True)
    preferred = ", ".join(
        m for m in ("gpt-5.2", "gpt-5.1", "gpt-5", "gpt-5-mini", "gpt-4.1-mini")
        if m in models
    ) or "не найдены"
    await update.effective_message.reply_text(
        "💬 General GPT Router diagnostic\n"
        f"version={VERSION}\n"
        "transport=official_openai_responses\n"
        f"enabled={_flag('GENERAL_TEXT_ROUTER_ENABLED', True)}\n"
        f"tier={tier}\n"
        f"default_model={model}\n"
        f"default_effort={effort}\n"
        f"default_max_output={max_output}\n"
        f"base_url={_base_url()}\n"
        f"key_source={_key_source(mod)}\n"
        f"key_fingerprint={_fingerprint(mod)}\n"
        f"available_preferred={preferred}\n"
        f"last_route={_LAST_ROUTE or '—'}"
    )


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception:
        return
    if getattr(ApplicationBuilder, "_general_router_v114_hooked", False):
        return

    original_build = ApplicationBuilder.build

    def build(self, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, "_general_router_v114_handlers", False):
            app.add_handler(CommandHandler("diag_text", _diag_text), group=-3)
            setattr(app, "_general_router_v114_handlers", True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, "_general_router_v114_hooked", True)


def patch_runtime(mod: Any) -> bool:
    if getattr(mod, PATCH_FLAG, False):
        mod.PATCH_VERSION = VERSION
        mod.GENERAL_TEXT_ROUTER_VERSION = VERSION
        return True
    if not hasattr(mod, "ask_openai_text") or not hasattr(mod, "ask_openai_vision"):
        return False

    original_text = mod.ask_openai_text
    original_vision = mod.ask_openai_vision

    async def ask_openai_text(
        user_text: str,
        web_ctx: str = "",
        user_id: int | None = None,
        chat_id: int | None = None,
        extra_system: str = "",
    ) -> str:
        value = _clean(user_text, 32000)
        if not value:
            return "Пустой запрос."
        if not _flag("GENERAL_TEXT_ROUTER_ENABLED", True):
            return await original_text(user_text, web_ctx, user_id, chat_id, extra_system)

        tier = _tier(mod, user_id)
        model, effort, max_output, complex_request = _model_plan(tier, value)

        system = str(getattr(mod, "SYSTEM_PROMPT", "") or "")
        with contextlib.suppress(Exception):
            system += "\n\n" + str(mod._current_date_system_text())
        if extra_system:
            system += "\n\n" + _clean(extra_system, 4000)
        if web_ctx:
            system += (
                "\n\nКонтекст из live-поиска. Используй только релевантные факты, "
                "не выдумывай отсутствующие детали и явно отличай источник от вывода:\n"
                + _clean(web_ctx, 16000)
            )
        system += (
            "\n\nОтвечай полезно и точно. Не раскрывай внутренний маршрут модели. "
            f"Уровень обслуживания: {tier}. "
            + ("Запрос сложный: проведи более глубокую проверку вывода." if complex_request else "")
        )

        input_messages: list[dict[str, Any]] = []
        if (
            bool(getattr(mod, "CHAT_MEMORY_ENABLED", False))
            and user_id
            and chat_id
            and hasattr(mod, "_chat_memory_recent")
        ):
            with contextlib.suppress(Exception):
                recent = mod._chat_memory_recent(
                    user_id,
                    chat_id,
                    int(getattr(mod, "CHAT_MEMORY_MAX_MESSAGES", 16)),
                )
                for message in recent or []:
                    if not isinstance(message, dict):
                        continue
                    role = message.get("role")
                    content = _clean(message.get("content"), 10000)
                    if role in {"user", "assistant"} and content:
                        input_messages.append({"role": role, "content": content})
        input_messages.append({"role": "user", "content": value})

        try:
            return await _responses_call(
                mod,
                system,
                input_messages,
                model,
                effort,
                max_output,
            )
        except Exception as exc:
            _log(mod, "error", "balanced general route failed: %r", exc)
            if _flag("GENERAL_ALLOW_LEGACY_FALLBACK", False):
                return await original_text(user_text, web_ctx, user_id, chat_id, extra_system)
            return (
                "⚠️ Сейчас не получилось получить ответ от официальной модели OpenAI. "
                "Повторите запрос немного позже."
            )

    async def ask_openai_vision(user_text: str, img_b64: str, mime: str) -> str:
        if not _flag("GENERAL_TEXT_ROUTER_ENABLED", True):
            return await original_vision(user_text, img_b64, mime)
        prompt = _clean(
            user_text or "Подробно опиши изображение и распознай значимый текст.",
            10000,
        )
        model = os.environ.get("GENERAL_VISION_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
        instructions = str(getattr(mod, "VISION_SYSTEM_PROMPT", "") or "")
        content = [
            {"type": "input_text", "text": prompt},
            {
                "type": "input_image",
                "image_url": f"data:{mime};base64,{img_b64}",
                "detail": "high",
            },
        ]
        try:
            return await _responses_call(
                mod,
                instructions,
                [{"role": "user", "content": content}],
                model,
                "low",
                2600,
            )
        except Exception as exc:
            _log(mod, "error", "balanced vision route failed: %r", exc)
            if _flag("GENERAL_ALLOW_LEGACY_FALLBACK", False):
                return await original_vision(user_text, img_b64, mime)
            return "Не удалось проанализировать изображение через официальный OpenAI API."

    mod.ask_openai_text = ask_openai_text
    mod.ask_openai_vision = ask_openai_vision
    mod.GENERAL_TEXT_ROUTER_VERSION = VERSION
    mod.PATCH_VERSION = VERSION
    setattr(mod, PATCH_FLAG, True)
    _log(mod, "info", "Balanced official OpenAI router installed: %s", VERSION)
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

    threading.Thread(
        target=worker,
        daemon=True,
        name="general-router-v114",
    ).start()


__all__ = [
    "VERSION",
    "install_builder_hook",
    "patch_runtime",
    "install_async",
]
