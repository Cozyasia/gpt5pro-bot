# -*- coding: utf-8 -*-
"""Celebrity Selfie v150: Comet-first scene generation with auth circuit breakers.

v149 correctly rejected fake/non-human layers, but production still had a single
point of failure: the empty background route depended on a stale Gemini key.
v150 makes the already configured CometAPI image endpoint the primary scene
provider, keeps BFL/FLUX and Gemini as true fallbacks, and permanently skips a
provider for the current process after an authentication failure. Placeholder
backgrounds remain disabled: the bot either produces a real scene or fails
without charging for an undelivered result.
"""
from __future__ import annotations

import asyncio
import base64
import os
import time
from io import BytesIO
from typing import Any, Awaitable, Callable, Iterable

import httpx
from PIL import Image, ImageOps

import celebrity_selfie_v139 as v139
import celebrity_selfie_v142 as v142
import celebrity_selfie_v143 as v143
import celebrity_selfie_v147 as v147
import celebrity_selfie_v149 as v149

VERSION = "v150-comet-scene-failover-2026-07-21"
_GROUP = -2_100_001_300
_BUILDER_FLAG = "_celebrity_selfie_v150_builder"
_HANDLER_FLAG = "_celebrity_selfie_v150_handlers"
_LAST_RUN_DEBUG: dict[str, Any] = {}
_AUTH_DISABLED: dict[str, str] = {}


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().casefold() not in {"0", "false", "no", "off", ""}


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    return v139._integer(name, default, minimum, maximum)


def _safe_error(exc: BaseException) -> str:
    return v139._safe_error(exc)


def _open_rgb(raw: bytes) -> Image.Image:
    if not raw:
        raise ValueError("empty image")
    with Image.open(BytesIO(raw)) as opened:
        return ImageOps.exif_transpose(opened).convert("RGB")


def _encode_jpeg(image: Image.Image, quality: int = 95) -> bytes:
    out = BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def _normalise_output(raw: bytes, aspect: str) -> bytes:
    image = _open_rgb(raw)
    target = v147._aspect_size(aspect, long_side=1280)
    if image.size != target:
        image = ImageOps.fit(image, target, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    return _encode_jpeg(image, 95)


def _scene_provider_order() -> list[str]:
    raw = os.environ.get("CELEBRITY_V150_SCENE_PROVIDERS") or "comet,flux,gemini"
    allowed = {"comet", "flux", "gemini"}
    result: list[str] = []
    for item in raw.split(","):
        provider = item.strip().casefold()
        if provider in allowed and provider not in result:
            result.append(provider)
    return result or ["comet", "flux", "gemini"]


def _looks_auth_error(text: str) -> bool:
    lowered = str(text or "").casefold()
    tokens = (
        "api key not valid", "invalid api key", "invalid_api_key", "incorrect api key",
        "unauthorized", "not authorized", "authentication", "permission denied",
        "http 401", "http 403", "status 401", "status 403",
    )
    return any(token in lowered for token in tokens)


def _disable_auth(provider: str, reason: str) -> None:
    _AUTH_DISABLED[provider] = str(reason or "authentication failed")[:500]


def _comet_key() -> str:
    return str(os.environ.get("COMET_API_KEY") or os.environ.get("COMETAPI_KEY") or "").strip()


def _comet_size(aspect: str) -> str:
    safe = str(aspect or "4:5")
    if safe in {"1:1"}:
        return "1024x1024"
    try:
        left, right = safe.split(":", 1)
        landscape = float(left) / max(1.0, float(right)) >= 1.0
    except Exception:
        landscape = False
    return "1536x1024" if landscape else "1024x1536"


def _comet_payload_variants(prompt: str, aspect: str) -> list[tuple[str, dict[str, Any]]]:
    model = str(
        os.environ.get("CELEBRITY_V150_COMET_IMAGE_MODEL")
        or os.environ.get("COMET_IMAGE_GEN_MODEL")
        or "gpt-image-1"
    ).strip()
    size = _comet_size(aspect)
    return [
        ("gpt-image-default-b64", {
            "model": model, "prompt": prompt, "size": size, "quality": "medium", "n": 1,
        }),
        ("gpt-image-minimal", {
            "model": model, "prompt": prompt, "size": size, "n": 1,
        }),
        ("openai-compatible-b64", {
            "model": model, "prompt": prompt, "size": size, "n": 1, "response_format": "b64_json",
        }),
    ]


def _walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _inline_image(data: Any) -> bytes | None:
    keys = ("b64_json", "b64", "base64", "image_base64", "imageBase64")
    for node in _walk(data):
        if not isinstance(node, dict):
            continue
        for key in keys:
            value = node.get(key)
            if isinstance(value, str) and len(value) > 100:
                try:
                    encoded = value.split(",", 1)[-1] if value.startswith("data:") else value
                    raw = base64.b64decode(encoded, validate=False)
                    if raw:
                        _open_rgb(raw)
                        return raw
                except Exception:
                    continue
    return None


def _image_url(data: Any) -> str | None:
    for node in _walk(data):
        if isinstance(node, str) and node.startswith(("https://", "http://")):
            return node
        if isinstance(node, dict):
            for key in ("url", "image_url", "imageUrl", "download_url", "downloadUrl"):
                value = node.get(key)
                if isinstance(value, str) and value.startswith(("https://", "http://")):
                    return value
    return None


async def _comet_scene(prompt: str, aspect: str, debug: dict[str, Any]) -> bytes:
    if "comet" in _AUTH_DISABLED:
        raise v139.PipelineError("auth_or_key", f"Comet disabled after authentication failure: {_AUTH_DISABLED['comet']}")
    key = _comet_key()
    if not key:
        raise v139.PipelineError("auth_or_key", "COMET_API_KEY missing")
    base_url = str(os.environ.get("COMET_BASE_URL") or "https://api.cometapi.com").rstrip("/")
    path = str(os.environ.get("COMET_IMAGE_GEN_PATH") or "/v1/images/generations")
    if not path.startswith("/"):
        path = "/" + path
    timeout_s = _integer("CELEBRITY_V150_COMET_TIMEOUT_S", 240, 60, 900)
    errors: list[str] = []
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=35, read=timeout_s, write=120),
        follow_redirects=True,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json", "Content-Type": "application/json"},
    ) as client:
        for schema, payload in _comet_payload_variants(prompt, aspect):
            debug.setdefault("comet_schema_attempts", []).append({
                "schema": schema, "model": payload.get("model"), "size": payload.get("size"), "path": path,
            })
            try:
                response = await client.post(f"{base_url}{path}", json=payload)
                try:
                    data: Any = response.json()
                except Exception:
                    data = {"raw": response.text[:1200]}
                if response.status_code >= 400:
                    detail = str(data)[:900]
                    message = f"{schema}: HTTP {response.status_code}: {detail}"
                    errors.append(message)
                    if response.status_code in {401, 403} or _looks_auth_error(message):
                        _disable_auth("comet", message)
                        raise v139.PipelineError("auth_or_key", message)
                    continue
                inline = _inline_image(data)
                if inline:
                    return _normalise_output(inline, aspect)
                url = _image_url(data)
                if url:
                    downloaded = await client.get(url, headers={"Accept": "image/*,*/*"})
                    if downloaded.status_code < 400 and downloaded.content:
                        return _normalise_output(downloaded.content, aspect)
                    errors.append(f"{schema}: image download HTTP {downloaded.status_code}")
                    continue
                errors.append(f"{schema}: response contained no image")
            except v139.PipelineError:
                raise
            except Exception as exc:
                message = f"{schema}: {_safe_error(exc)}"
                errors.append(message)
                if _looks_auth_error(message):
                    _disable_auth("comet", message)
                    raise v139.PipelineError("auth_or_key", message) from exc
    raise RuntimeError("Comet image scene failed: " + " | ".join(errors[-6:])[:1800])


async def _gemini_scene(prompt: str, aspect: str, mod: Any, debug: dict[str, Any], variant: int) -> bytes:
    if "gemini" in _AUTH_DISABLED:
        raise v139.PipelineError("auth_or_key", f"Gemini disabled after authentication failure: {_AUTH_DISABLED['gemini']}")
    models = v139.selfie.previous._gemini_models(mod) or ["gemini-3-pro-image", "gemini-3.1-flash-image"]
    model = models[variant % len(models)]
    try:
        return await v149._gemini_scene_normalized(mod, model, prompt, aspect, debug)
    except Exception as exc:
        message = _safe_error(exc)
        if _looks_auth_error(message):
            _disable_auth("gemini", message)
            raise v139.PipelineError("auth_or_key", message) from exc
        raise


async def _make_background_candidates(
    mod: Any,
    scene: str,
    aspect: str,
    user_photo: bytes,
    debug: dict[str, Any],
) -> list[dict[str, Any]]:
    safe_aspect = v143.v144._normalise_aspect(aspect) if hasattr(v143, "v144") else str(aspect or "4:5")
    # v147 already owns the canonical normalizer; this protects older import layouts.
    try:
        safe_aspect = v147.v144._normalise_aspect(aspect)
    except Exception:
        pass
    debug["scene_aspect_requested"] = str(aspect or "-")
    debug["scene_aspect_normalized"] = safe_aspect
    debug["scene_generation_contract"] = "comet-primary+flux+gemini-auth-failover+no-placeholder"
    debug["scene_provider_order"] = _scene_provider_order()
    debug["provider_auth_circuits"] = dict(_AUTH_DISABLED)
    debug.setdefault("background_attempts", [])
    debug.setdefault("scene_candidates", [])
    candidates: list[dict[str, Any]] = []

    async def evaluate(label: str, provider: str, factory: Callable[[], Awaitable[bytes]]) -> bool:
        stage = v139._stage_start(debug, label, provider, aspect=safe_aspect, people=0)
        attempt: dict[str, Any] = {"stage": label, "provider": provider, "aspect": safe_aspect}
        debug["background_attempts"].append(attempt)
        try:
            raw = await factory()
            problem = v147._background_problem(raw)
            if problem:
                raise v139.PipelineError("structural_qc", problem)
            vision = await v147._background_vision_qc(mod, raw, scene)
            if not vision.get("accepted"):
                raise v139.PipelineError("scene_generation", str(vision.get("reason") or "empty background rejected"))
            metrics = v139._image_metrics(raw)
            score = (
                min(100.0, float(metrics.get("short_side") or 0) / 12.0)
                + min(100.0, float(metrics.get("contrast") or 0) * 2.0)
                + float(vision.get("quality") or 65.0)
            ) / 3.0
            row = {
                "label": label, "provider": provider, "score": round(score, 2), "output": raw,
                "aspect": safe_aspect, "people": 0, "vision_background_qc": vision,
            }
            candidates.append(row)
            debug["scene_candidates"].append({key: value for key, value in row.items() if key != "output"})
            attempt.update(status="ok", score=row["score"])
            v139._stage_finish(stage, "ok", score=row["score"], bytes=len(raw), people=0)
            return True
        except Exception as exc:
            message = _safe_error(exc)
            attempt.update(status="error", error=message[:700])
            v139._record_error(debug, stage, exc)
            return False

    for provider in _scene_provider_order():
        if provider in _AUTH_DISABLED:
            debug["background_attempts"].append({
                "stage": f"v150_{provider}_auth_circuit", "provider": provider,
                "status": "skipped", "reason": _AUTH_DISABLED[provider],
            })
            continue
        if provider == "comet":
            if not _comet_key():
                continue
            count = _integer("CELEBRITY_V150_COMET_BACKGROUNDS", 2, 1, 3)
            for index in range(count):
                prompt = v147._background_prompt(scene, safe_aspect, index)
                await evaluate(
                    f"v150_background_comet_{index + 1}",
                    f"comet:{os.environ.get('CELEBRITY_V150_COMET_IMAGE_MODEL') or os.environ.get('COMET_IMAGE_GEN_MODEL') or 'gpt-image-1'}",
                    lambda prompt=prompt: _comet_scene(prompt, safe_aspect, debug),
                )
            if candidates:
                break
        elif provider == "flux":
            if not v139.selfie._bfl_key():
                continue
            count = _integer("CELEBRITY_V150_FLUX_BACKGROUNDS", 1, 1, 2)
            for index in range(count):
                prompt = v147._background_prompt(scene, safe_aspect, index + 2)
                await evaluate(
                    f"v150_background_flux_{index + 1}",
                    f"bfl:{os.environ.get('CELEBRITY_FLUX_MODEL') or 'flux-2-pro'}",
                    lambda prompt=prompt: v139.selfie._flux_edit(prompt, [], safe_aspect),
                )
            if candidates:
                break
        elif provider == "gemini":
            if not v139.selfie.previous._gemini_key(mod):
                continue
            count = _integer("CELEBRITY_V150_GEMINI_BACKGROUNDS", 2, 1, 3)
            for index in range(count):
                prompt = v147._background_prompt(scene, safe_aspect, index)
                ok = await evaluate(
                    f"v150_background_gemini_{index + 1}",
                    "gemini:fallback",
                    lambda prompt=prompt, index=index: _gemini_scene(prompt, safe_aspect, mod, debug, index),
                )
                if not ok and "gemini" in _AUTH_DISABLED:
                    break
            if candidates:
                break

    debug["provider_auth_circuits"] = dict(_AUTH_DISABLED)
    candidates.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    return candidates


async def _run_v150_generation(
    mod: Any,
    user_photo: bytes,
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    previous_result: bytes | None = None,
    *,
    additional_user_refs: list[bytes] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    global _LAST_RUN_DEBUG
    started = time.time()
    contract = {
        "version": VERSION,
        "architecture": "comet-first-real-scene+verified-visible-dual-human-layers",
        "scene_provider_order": _scene_provider_order(),
        "scene_auth_circuit_breaker": "enabled",
        "local_placeholder_background": "disabled",
        "user_face_generation": "disabled",
        "celebrity_face_generation": "disabled",
        "face_swap": "disabled",
    }
    try:
        output, debug = await v149._run_v149_generation(
            mod, user_photo, celebrity_refs, celebrity_name, scene,
            previous_result=previous_result, additional_user_refs=additional_user_refs,
        )
        debug = dict(debug or {})
        debug.update(contract)
        debug["provider_auth_circuits"] = dict(_AUTH_DISABLED)
        debug["v150_duration_s"] = round(time.time() - started, 2)
        _LAST_RUN_DEBUG = debug
        for module in (v149, v147, v143, v142, v139):
            module._LAST_RUN_DEBUG = debug
        return output, debug
    except Exception as exc:
        debug = dict(getattr(exc, "debug", None) or {})
        debug.update(contract)
        debug["provider_auth_circuits"] = dict(_AUTH_DISABLED)
        debug["v150_duration_s"] = round(time.time() - started, 2)
        _LAST_RUN_DEBUG = debug
        for module in (v149, v147, v143, v142, v139):
            module._LAST_RUN_DEBUG = debug
        if isinstance(exc, v139.PipelineError):
            exc.debug = debug
        raise


async def _run_compat(
    mod: Any,
    user_photo: bytes,
    celebrity_refs: list[bytes],
    celebrity_name: str,
    scene: str,
    previous_result: bytes | None = None,
    *,
    additional_user_refs: list[bytes] | None = None,
) -> bytes:
    output, _ = await _run_v150_generation(
        mod, user_photo, celebrity_refs, celebrity_name, scene,
        previous_result=previous_result, additional_user_refs=additional_user_refs,
    )
    return output


def _patch_version_contract() -> None:
    try:
        import neyrobot_prod
        from neyrobot_prod import bootstrap, versioning
        neyrobot_prod.VERSION = VERSION
        bootstrap.VERSION = VERSION
        versioning.VERSION = VERSION
    except Exception:
        pass


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    session = v139.selfie.engine._session(context, create=False) or {}
    debug = session.get("v142_debug") or session.get("v139_debug") or _LAST_RUN_DEBUG or {}
    lines = [
        f"📸 Celebrity Selfie / {VERSION}",
        "architecture=comet_first_scene+verified_visible_dual_human_layers",
        f"scene_provider_order={','.join(_scene_provider_order())}",
        f"comet={'ready' if bool(_comet_key()) else 'missing'}",
        f"flux={'ready' if bool(v139.selfie._bfl_key()) else 'optional-missing'}",
        f"gemini={'circuit-open' if 'gemini' in _AUTH_DISABLED else 'fallback'}",
        f"provider_auth_circuits={str(_AUTH_DISABLED or '-')[:1200]}",
        "local_placeholder_background=disabled",
        "visible_human_layer_proof=required",
        f"run_id={debug.get('run_id') or '-'}",
        f"state={session.get('state') or '-'}",
        f"scene_candidates={len(debug.get('scene_candidates') or [])}",
        f"background_attempts={str(debug.get('background_attempts') or '-')[:1800]}",
        f"failure_class={debug.get('failure_class') or '-'}",
        f"last_error={session.get('last_generation_error') or '-'}",
    ]
    text = "\n".join(lines)
    for offset in range(0, len(text), 3900):
        await update.effective_message.reply_text(text[offset:offset + 3900])
    raise ApplicationHandlerStop


def install() -> None:
    v149.install()
    os.environ["CELEBRITY_V147_SCENE_PROVIDERS"] = "comet,flux,gemini"
    os.environ["CELEBRITY_V147_LOCAL_BACKGROUND_FALLBACK"] = "0"
    os.environ.setdefault("CELEBRITY_V150_SCENE_PROVIDERS", "comet,flux,gemini")
    os.environ.setdefault("CELEBRITY_V150_COMET_BACKGROUNDS", "2")
    os.environ.setdefault("CELEBRITY_V150_COMET_TIMEOUT_S", "240")
    os.environ.setdefault("CELEBRITY_V150_FLUX_BACKGROUNDS", "1")
    os.environ.setdefault("CELEBRITY_V150_GEMINI_BACKGROUNDS", "2")

    v142._make_plate_candidates = _make_background_candidates
    v147._make_background_candidates = _make_background_candidates
    v139.selfie._run_v150_generation = _run_v150_generation
    v139.selfie.engine._run_multi_reference_generation = _run_compat
    v139.selfie.engine._diag = _diag
    _patch_version_contract()


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        install()
        if not getattr(app, _HANDLER_FLAG, False):
            for command in (
                "diag_selfie_v150", "diag_selfie_v149", "diag_selfie_v148",
                "diag_selfie_v147", "diag_selfie_v146", "diag_selfie_v145",
                "diag_selfie_v144", "diag_selfie_v143", "diag_celebrity_flow", "diag_brand",
            ):
                app.add_handler(CommandHandler(command, _diag), group=_GROUP)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


def install_early() -> None:
    install()
    install_builder_hook()


__all__ = [
    "VERSION", "install", "install_early", "install_builder_hook",
    "_scene_provider_order", "_looks_auth_error", "_comet_payload_variants",
    "_inline_image", "_image_url", "_comet_scene", "_make_background_candidates",
    "_run_v150_generation", "_diag",
]
