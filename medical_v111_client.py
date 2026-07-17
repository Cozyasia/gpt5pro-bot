# -*- coding: utf-8 -*-
"""Direct OpenAI Responses API client for the medical engine v112."""
from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import sys
from typing import Any

import httpx

from medical_v111_prompts import EXTRACT_SYSTEM

PRICES = {
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.6-luna": (1.00, 6.00),
    "gpt-5.6-terra": (2.50, 15.00),
    "gpt-5.6-sol": (5.00, 30.00),
    "gpt-5.6": (5.00, 30.00),
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
}


def clean(value: Any, limit: int = 60000) -> str:
    text = str(value or "").replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text).strip()
    return text[:limit]


def plain(value: Any) -> str:
    text = clean(value)
    text = re.sub(r"(?m)^#{1,6}\s*", "", text).replace("**", "")
    return re.sub(r"(?m)^\s*[-–—]\s+", "• ", text).strip()


def split_text(text: str, limit: int = 3800) -> list[str]:
    rest, result = plain(text), []
    while len(rest) > limit:
        cut = rest.rfind("\n\n", 0, limit)
        if cut < limit // 3:
            cut = rest.rfind("\n", 0, limit)
        if cut < limit // 4:
            cut = limit
        result.append(rest[:cut].strip())
        rest = rest[cut:].lstrip()
    if rest:
        result.append(rest)
    return result or ["Не удалось сформировать медицинский разбор."]


def flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() not in {"0", "false", "no", "off"}


def int_env(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)) or default)
    except Exception:
        value = default
    return max(low, min(high, value))


def log(mod: Any, level: str, message: str, *args: Any) -> None:
    logger = getattr(mod, "log", None)
    if logger:
        with contextlib.suppress(Exception):
            getattr(logger, level)(message, *args)
            return
    with contextlib.suppress(Exception):
        print(message % args if args else message, file=sys.stderr)


def api_key(mod: Any) -> str:
    return (
        os.environ.get("MEDICAL_OPENAI_API_KEY", "").strip()
        or str(getattr(mod, "OPENAI_API_KEY", "") or "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
    )


def base_url() -> str:
    return (os.environ.get("MEDICAL_OPENAI_BASE_URL") or "https://api.openai.com/v1").strip().rstrip("/")


def user_tier(mod: Any, user: Any) -> str:
    user_id = int(getattr(user, "id", 0) or 0)
    username = str(getattr(user, "username", "") or "")
    with contextlib.suppress(Exception):
        if mod.is_unlimited(user_id, username):
            return "ultimate"
    with contextlib.suppress(Exception):
        tier = str(mod.get_subscription_tier(user_id) or "free").lower()
        if tier in {"free", "start", "pro", "ultimate"}:
            return tier
    return "free"


def model_plan(tier: str) -> dict[str, Any]:
    premium = tier in {"pro", "ultimate"}
    reason_key = (
        "MEDICAL_REASONING_MODEL_ULTIMATE" if tier == "ultimate"
        else "MEDICAL_REASONING_MODEL_PRO" if premium
        else "MEDICAL_REASONING_MODEL_BASIC"
    )
    effort_key = (
        "MEDICAL_REASONING_EFFORT_ULTIMATE" if tier == "ultimate"
        else "MEDICAL_REASONING_EFFORT_PRO" if premium
        else "MEDICAL_REASONING_EFFORT_BASIC"
    )
    effort = os.environ.get(effort_key, "high" if tier == "ultimate" else "medium").strip().lower()
    default_reason = "gpt-5.6-sol" if tier == "ultimate" else "gpt-5.6-terra" if premium else "gpt-5.6-luna"
    return {
        "extract": os.environ.get("MEDICAL_EXTRACT_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini",
        "reason": os.environ.get(reason_key, default_reason).strip() or default_reason,
        "audit": os.environ.get("MEDICAL_AUDIT_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini",
        "effort": effort if effort in {"none", "low", "medium", "high", "xhigh"} else "medium",
        "max_output": int_env("MEDICAL_MAX_OUTPUT_PREMIUM" if premium else "MEDICAL_MAX_OUTPUT_BASIC", 5200 if premium else 3600, 1400, 9000),
    }


def fallbacks(primary: str, kind: str) -> list[str]:
    defaults = {
        "extract": ["gpt-5.4-mini", "gpt-5-mini", "gpt-5"],
        "reason": ["gpt-5.6-terra", "gpt-5.4", "gpt-5", "gpt-5.4-mini"],
        "audit": ["gpt-5.4-mini", "gpt-5-mini", "gpt-5"],
    }[kind]
    custom = [item.strip() for item in os.environ.get(f"MEDICAL_{kind.upper()}_FALLBACKS", "").split(",") if item.strip()]
    result = []
    for model in [primary, *custom, *defaults]:
        if model and model not in result:
            result.append(model)
    return result


def parse_json(text: str) -> dict:
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean(text, 120000), flags=re.I | re.S).strip()
    with contextlib.suppress(Exception):
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        with contextlib.suppress(Exception):
            data = json.loads(raw[start:end + 1])
            if isinstance(data, dict):
                return data
    return {}


def _response_text(data: dict) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    result: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"}:
                value = content.get("text")
                if isinstance(value, str) and value.strip():
                    result.append(value.strip())
    return "\n".join(result).strip()


def _usage(model: str, data: dict) -> dict:
    usage = data.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    input_price, output_price = PRICES.get(model, (0.0, 0.0))
    cost = (input_tokens * input_price + output_tokens * output_price) / 1_000_000
    return {"model": model, "input": input_tokens, "output": output_tokens, "cost_usd": round(cost, 6)}


def _responses_input(user_content: Any) -> Any:
    if isinstance(user_content, str):
        return user_content
    if not isinstance(user_content, list):
        return clean(user_content)
    converted: list[dict[str, Any]] = []
    for item in user_content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in {"text", "input_text"}:
            converted.append({"type": "input_text", "text": clean(item.get("text"), 120000)})
        elif item_type in {"image_url", "input_image"}:
            image = item.get("image_url")
            if isinstance(image, dict):
                url = image.get("url") or image.get("image_url")
                detail = image.get("detail") or item.get("detail") or "high"
            else:
                url = image
                detail = item.get("detail") or "high"
            if url:
                converted.append({"type": "input_image", "image_url": str(url), "detail": detail})
    return [{"role": "user", "content": converted}]


async def call_model(
    mod: Any,
    run: dict,
    kind: str,
    models: list[str],
    system: str,
    user_content: Any,
    effort: str,
    max_tokens: int,
    json_mode: bool = False,
) -> tuple[str, str]:
    if not api_key(mod):
        raise RuntimeError("MEDICAL_OPENAI_API_KEY/OPENAI_API_KEY is missing")
    headers = {"Authorization": f"Bearer {api_key(mod)}", "Content-Type": "application/json"}
    last_error: Exception | None = None
    for model in models:
        body: dict[str, Any] = {
            "model": model,
            "instructions": system,
            "input": _responses_input(user_content),
            "max_output_tokens": max_tokens,
            "reasoning": {"effort": effort},
            "store": False,
        }
        if json_mode:
            body["text"] = {"format": {"type": "json_object"}}
        try:
            timeout = httpx.Timeout(connect=20, read=float(os.environ.get("MEDICAL_READ_TIMEOUT", "240")), write=90, pool=20)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(base_url() + "/responses", headers=headers, json=body)
            request_id = response.headers.get("x-request-id", "")
            if response.status_code >= 400:
                detail = response.text[:900]
                raise RuntimeError(f"HTTP {response.status_code}: {detail}; request_id={request_id}")
            data = response.json()
            text = _response_text(data)
            if not text:
                status = data.get("status")
                incomplete = data.get("incomplete_details") or data.get("error") or {}
                raise RuntimeError(f"empty Responses API output; status={status}; details={incomplete}; request_id={request_id}")
            run.setdefault("calls", []).append(_usage(model, data))
            run.setdefault("transports", []).append(f"{kind}:responses")
            if model != models[0]:
                run.setdefault("fallbacks", []).append(f"{kind}:{model}")
            return text, model
        except Exception as exc:
            last_error = exc
            log(mod, "warning", "medical %s model %s failed via Responses API: %r", kind, model, exc)
    raise RuntimeError(f"all {kind} models failed via Responses API: {last_error!r}")


def normalize_extraction(data: dict) -> dict:
    result = dict(data or {})
    for key in ("specialties", "body_regions", "impression", "recommendations_in_source", "unreadable_fragments", "contradictions"):
        value = result.get(key, [])
        if isinstance(value, str):
            value = [value]
        result[key] = [clean(item, 800) for item in value[:50]] if isinstance(value, list) else []
    result["document_type"] = clean(result.get("document_type"), 80) or "other"
    result["document_title"] = clean(result.get("document_title"), 160) or "Медицинский документ"
    result["document_date"] = clean(result.get("document_date"), 30)
    result["image_quality"] = clean(result.get("image_quality"), 30) or "acceptable"
    try:
        result["confidence"] = max(0.0, min(1.0, float(result.get("confidence") or 0)))
    except Exception:
        result["confidence"] = 0.0
    findings = []
    for item in result.get("findings", []) if isinstance(result.get("findings"), list) else []:
        if not isinstance(item, dict):
            continue
        measurements = item.get("measurements", []) if isinstance(item.get("measurements"), list) else []
        item["measurements"] = [
            {
                "name": clean(m.get("name"), 150), "value": clean(m.get("value"), 100),
                "unit": clean(m.get("unit"), 60), "reference": clean(m.get("reference"), 180),
            }
            for m in measurements[:30] if isinstance(m, dict)
        ]
        findings.append(item)
    result["findings"] = findings[:100]
    return result


async def extract_image(mod: Any, run: dict, raw: bytes, mime: str, goal: str, track: str, model: str) -> dict:
    prompt = f"User goal: {goal or 'detailed explanation'}\nSelected track: {track or 'automatic'}\nRead the attached image in high detail. If it is a raw medical scan rather than a written report, state that limitation."
    user_content = [
        {"type": "input_text", "text": prompt},
        {"type": "input_image", "image_url": f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}", "detail": "high"},
    ]
    text, _ = await call_model(mod, run, "extract", fallbacks(model, "extract"), EXTRACT_SYSTEM, user_content, "low", int_env("MEDICAL_EXTRACT_MAX_OUTPUT", 4200, 1800, 7500), True)
    data = parse_json(text)
    if not data:
        raise RuntimeError("extract model returned no valid JSON object")
    return normalize_extraction(data)


async def extract_text(mod: Any, run: dict, source: str, goal: str, track: str, model: str) -> dict:
    prompt = f"User goal: {goal or 'detailed explanation'}\nSelected track: {track or 'automatic'}\nSOURCE:\n{source[:50000]}"
    text, _ = await call_model(mod, run, "extract", fallbacks(model, "extract"), EXTRACT_SYSTEM, prompt, "low", int_env("MEDICAL_EXTRACT_MAX_OUTPUT", 4200, 1800, 7500), True)
    data = parse_json(text)
    if not data:
        raise RuntimeError("extract model returned no valid JSON object")
    return normalize_extraction(data)
