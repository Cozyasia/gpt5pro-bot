# -*- coding: utf-8 -*-
"""Direct official OpenAI Responses API client for the medical engine v113."""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import re
import sys
import time
from typing import Any

import httpx

from medical_v111_prompts import EXTRACT_SYSTEM

PRICES = {
    "gpt-5.2": (1.75, 14.00),
    "gpt-5.1": (1.25, 10.00),
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
}

_STABLE_BY_KIND = {
    "extract": ["gpt-5-mini", "gpt-4.1-mini", "gpt-4o-mini", "gpt-5"],
    "reason": ["gpt-5.2", "gpt-5.1", "gpt-5", "gpt-5-mini", "gpt-4.1"],
    "audit": ["gpt-5-mini", "gpt-5", "gpt-4.1-mini", "gpt-4o-mini"],
}

_NON_API_MODEL_PATTERNS = (
    re.compile(r"^gpt-5\.4(?:-|$)", re.I),
    re.compile(r"^gpt-5\.6(?:-|$)", re.I),
    re.compile(r"(?:^|-)sol$", re.I),
    re.compile(r"(?:^|-)terra$", re.I),
    re.compile(r"(?:^|-)luna$", re.I),
)

_MODEL_CACHE: dict[str, Any] = {"at": 0.0, "models": [], "error": ""}


class MedicalAPIError(RuntimeError):
    def __init__(self, category: str, message: str, *, status: int = 0, request_id: str = "") -> None:
        super().__init__(message)
        self.category = category
        self.status = status
        self.request_id = request_id


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
        or os.environ.get("OPENAI_API_KEY", "").strip()
        or str(getattr(mod, "OPENAI_API_KEY", "") or "").strip()
        or os.environ.get("OPENAI_IMAGE_KEY", "").strip()
    )


def api_key_source(mod: Any) -> str:
    if os.environ.get("MEDICAL_OPENAI_API_KEY", "").strip():
        return "MEDICAL_OPENAI_API_KEY"
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return "OPENAI_API_KEY"
    if str(getattr(mod, "OPENAI_API_KEY", "") or "").strip():
        return "runtime OPENAI_API_KEY"
    if os.environ.get("OPENAI_IMAGE_KEY", "").strip():
        return "OPENAI_IMAGE_KEY"
    return "missing"


def key_fingerprint(mod: Any) -> str:
    value = api_key(mod)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10] if value else "—"


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
    default_reason = "gpt-5.2" if tier == "ultimate" else "gpt-5" if premium else "gpt-5-mini"
    return {
        "extract": os.environ.get("MEDICAL_EXTRACT_MODEL", "gpt-5-mini").strip() or "gpt-5-mini",
        "reason": os.environ.get(reason_key, default_reason).strip() or default_reason,
        "audit": os.environ.get("MEDICAL_AUDIT_MODEL", "gpt-5-mini").strip() or "gpt-5-mini",
        "effort": effort if effort in {"none", "low", "medium", "high", "xhigh"} else "medium",
        "max_output": int_env("MEDICAL_MAX_OUTPUT_PREMIUM" if premium else "MEDICAL_MAX_OUTPUT_BASIC", 5200 if premium else 3600, 1400, 9000),
    }


def _looks_non_api(model: str) -> bool:
    return any(pattern.search(model or "") for pattern in _NON_API_MODEL_PATTERNS)


def fallbacks(primary: str, kind: str) -> list[str]:
    custom = [item.strip() for item in os.environ.get(f"MEDICAL_{kind.upper()}_FALLBACKS", "").split(",") if item.strip()]
    result: list[str] = []
    for model in [primary, *custom, *_STABLE_BY_KIND[kind]]:
        if model and model not in result and not _looks_non_api(model):
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


def _headers(mod: Any) -> dict[str, str]:
    key = api_key(mod)
    if not key:
        raise MedicalAPIError("missing_key", "MEDICAL_OPENAI_API_KEY/OPENAI_API_KEY is missing")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _error_text(response: httpx.Response) -> tuple[str, str]:
    code = ""
    message = response.text[:1200]
    with contextlib.suppress(Exception):
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            code = clean(error.get("code") or error.get("type"), 100)
            message = clean(error.get("message") or message, 900)
    return code, message


async def available_models(mod: Any, force: bool = False) -> tuple[list[str], str]:
    now = time.monotonic()
    if not force and _MODEL_CACHE["models"] and now - float(_MODEL_CACHE["at"]) < 600:
        return list(_MODEL_CACHE["models"]), str(_MODEL_CACHE["error"])
    try:
        timeout = httpx.Timeout(connect=15, read=30, write=30, pool=15)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(base_url() + "/models", headers=_headers(mod))
        request_id = response.headers.get("x-request-id", "")
        if response.status_code >= 400:
            code, message = _error_text(response)
            category = "auth" if response.status_code in {401, 403} else "quota" if response.status_code == 429 else "models"
            raise MedicalAPIError(category, f"HTTP {response.status_code} {code}: {message}", status=response.status_code, request_id=request_id)
        data = response.json()
        models = sorted({str(item.get("id")) for item in data.get("data", []) if isinstance(item, dict) and item.get("id")})
        _MODEL_CACHE.update({"at": now, "models": models, "error": ""})
        return models, ""
    except Exception as exc:
        _MODEL_CACHE.update({"at": now, "models": [], "error": clean(exc, 600)})
        return [], clean(exc, 600)


async def _resolve_models(mod: Any, requested: list[str], kind: str) -> tuple[list[str], str]:
    available, discovery_error = await available_models(mod)
    candidates: list[str] = []
    for model in [*requested, *_STABLE_BY_KIND[kind]]:
        if model and model not in candidates and not _looks_non_api(model):
            candidates.append(model)
    if available:
        exact = [model for model in candidates if model in available]
        if exact:
            return exact, ""
        relevant = [model for model in _STABLE_BY_KIND[kind] if model in available]
        if relevant:
            return relevant, ""
        discovered = [
            model for model in available
            if re.match(r"^(gpt-5|gpt-4\.1|gpt-4o)(?:$|-)", model)
            and "audio" not in model and "realtime" not in model and "transcribe" not in model and "tts" not in model
        ]
        if discovered:
            return discovered[:6], ""
        raise MedicalAPIError("model", "No compatible GPT text/vision model is available for this API project")
    return candidates, discovery_error


def _request_variants(model: str, system: str, user_content: Any, effort: str,
                      max_tokens: int, json_mode: bool) -> list[dict[str, Any]]:
    base: dict[str, Any] = {
        "model": model,
        "instructions": system + ("\nReturn exactly one valid JSON object." if json_mode else ""),
        "input": _responses_input(user_content),
        "max_output_tokens": max_tokens,
        "store": False,
    }
    if effort != "none" and (model.startswith("gpt-5") or model.startswith("o")):
        base["reasoning"] = {"effort": effort}
    variants: list[dict[str, Any]] = []
    first = dict(base)
    if json_mode:
        first["text"] = {"format": {"type": "json_object"}}
    variants.append(first)
    if "reasoning" in first:
        second = dict(first)
        second.pop("reasoning", None)
        variants.append(second)
    if json_mode:
        plain_json = dict(base)
        plain_json.pop("reasoning", None)
        variants.append(plain_json)
    unique: list[dict[str, Any]] = []
    seen = set()
    for variant in variants:
        marker = json.dumps(variant, ensure_ascii=False, sort_keys=True)
        if marker not in seen:
            seen.add(marker)
            unique.append(variant)
    return unique


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
    requested = list(models)
    resolved, discovery_error = await _resolve_models(mod, requested, kind)
    if discovery_error:
        log(mod, "warning", "medical model discovery unavailable; using stable aliases: %s", discovery_error)
    last_error: Exception | None = None
    timeout = httpx.Timeout(connect=20, read=float(os.environ.get("MEDICAL_READ_TIMEOUT", "240")), write=90, pool=20)
    for model in resolved:
        variants = _request_variants(model, system, user_content, effort, max_tokens, json_mode)
        for variant_index, body in enumerate(variants, start=1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(base_url() + "/responses", headers=_headers(mod), json=body)
                request_id = response.headers.get("x-request-id", "")
                if response.status_code >= 400:
                    code, message = _error_text(response)
                    combined = f"{code} {message}".lower()
                    if response.status_code in {401, 403}:
                        raise MedicalAPIError("auth", f"HTTP {response.status_code}: {message}", status=response.status_code, request_id=request_id)
                    if response.status_code == 429 and any(token in combined for token in ("quota", "billing", "credit", "insufficient")):
                        raise MedicalAPIError("quota", f"HTTP 429: {message}", status=429, request_id=request_id)
                    if response.status_code == 404 or "model_not_found" in combined or "does not exist" in combined:
                        last_error = MedicalAPIError("model", f"Model {model} unavailable: {message}", status=response.status_code, request_id=request_id)
                        break
                    if response.status_code == 400 and variant_index < len(variants):
                        last_error = MedicalAPIError("request", f"HTTP 400: {message}", status=400, request_id=request_id)
                        continue
                    raise MedicalAPIError("request", f"HTTP {response.status_code}: {message}", status=response.status_code, request_id=request_id)
                data = response.json()
                text = _response_text(data)
                if not text:
                    status = data.get("status")
                    incomplete = data.get("incomplete_details") or data.get("error") or {}
                    raise MedicalAPIError("empty", f"empty Responses API output; status={status}; details={incomplete}; request_id={request_id}", request_id=request_id)
                run.setdefault("calls", []).append(_usage(model, data))
                run.setdefault("transports", []).append(f"{kind}:responses")
                if requested and model != requested[0]:
                    run.setdefault("fallbacks", []).append(f"{kind}:{model}")
                return text, model
            except MedicalAPIError as exc:
                last_error = exc
                log(mod, "warning", "medical %s model %s failed via Responses API [%s]: %s", kind, model, exc.category, exc)
                if exc.category in {"auth", "quota", "missing_key"}:
                    raise
                if exc.category == "model":
                    break
            except Exception as exc:
                last_error = exc
                log(mod, "warning", "medical %s model %s failed via Responses API: %r", kind, model, exc)
    if isinstance(last_error, MedicalAPIError):
        raise last_error
    raise MedicalAPIError("unavailable", f"all {kind} models failed via Responses API: {last_error!r}")


async def probe_api(mod: Any, force: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {
        "base_url": base_url(),
        "key_source": api_key_source(mod),
        "key_fingerprint": key_fingerprint(mod),
        "models_status": "not_tested",
        "responses_status": "not_tested",
        "selected_model": "",
        "available_preferred": [],
        "error": "",
    }
    models, error = await available_models(mod, force=force)
    if error:
        result["models_status"] = "error"
        result["error"] = error
        return result
    result["models_status"] = "ok"
    result["available_preferred"] = [m for m in ["gpt-5.2", "gpt-5.1", "gpt-5", "gpt-5-mini", "gpt-4.1-mini", "gpt-4o-mini"] if m in models]
    candidates = result["available_preferred"] or [m for m in models if m.startswith("gpt-")][:5]
    if not candidates:
        result["responses_status"] = "no_compatible_model"
        return result
    model = candidates[0]
    result["selected_model"] = model
    body = {"model": model, "input": "Reply with exactly OK", "max_output_tokens": 20, "store": False}
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(base_url() + "/responses", headers=_headers(mod), json=body)
        if response.status_code >= 400:
            code, message = _error_text(response)
            result["responses_status"] = f"http_{response.status_code}"
            result["error"] = f"{code}: {message}"
        else:
            text = _response_text(response.json())
            result["responses_status"] = "ok" if text else "empty"
    except Exception as exc:
        result["responses_status"] = "error"
        result["error"] = clean(exc, 600)
    return result


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
        raise MedicalAPIError("parse", "extract model returned no valid JSON object")
    return normalize_extraction(data)


async def extract_text(mod: Any, run: dict, source: str, goal: str, track: str, model: str) -> dict:
    prompt = f"User goal: {goal or 'detailed explanation'}\nSelected track: {track or 'automatic'}\nSOURCE:\n{source[:50000]}"
    text, _ = await call_model(mod, run, "extract", fallbacks(model, "extract"), EXTRACT_SYSTEM, prompt, "low", int_env("MEDICAL_EXTRACT_MAX_OUTPUT", 4200, 1800, 7500), True)
    data = parse_json(text)
    if not data:
        raise MedicalAPIError("parse", "extract model returned no valid JSON object")
    return normalize_extraction(data)
