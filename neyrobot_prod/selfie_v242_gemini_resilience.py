# -*- coding: utf-8 -*-
"""V242 resilient Google Gemini image caller for the terminal selfie pipeline.

This patch does not change the UI, scene/hero/body architecture or terminal face swap.
It only hardens the Gemini composition request against transient HTTP 429/5xx errors,
model instability and oversized 2K requests.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import random
from typing import Any

VERSION = "v242-resilient-gemini-composition-2026-08-06"
_INSTALLED = False
_ORIGINAL: Any | None = None


def _model_order(v229: Any) -> list[str]:
    configured = list(v229._models())
    extra_raw = (os.environ.get("GEMINI_SELFIE_FALLBACK_MODELS") or "gemini-3.1-flash-image,gemini-3-pro-image").strip()
    ordered: list[str] = []
    for model in configured + [x.strip() for x in extra_raw.split(",") if x.strip()]:
        if model and model not in ordered:
            ordered.append(model)
    return ordered


def _retryable(status: int) -> bool:
    return status in {408, 409, 425, 429, 500, 502, 503, 504}


async def resilient_call_google(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    import httpx
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as extractor
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229

    key = v229._key()
    if not key:
        raise RuntimeError("GEMINI_IMAGE_API_KEY is missing")

    prepared = [(label, *v229._prepare(raw)) for label, raw in labeled_images]
    timeout_s = max(300.0, float(os.environ.get("GEMINI_SELFIE_TIMEOUT_S", "420") or 420))
    timeout = httpx.Timeout(timeout_s, connect=45.0, read=timeout_s, write=180.0, pool=45.0)
    headers = {"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
    attempts_per_variant = max(1, int(os.environ.get("GEMINI_SELFIE_RETRIES_PER_VARIANT", "3") or 3))
    errors: list[str] = []
    models = _model_order(v229)

    # Try high quality first, then remove imageConfig, then use 1K. This keeps the
    # successful path unchanged while avoiding a hard failure on a transient 2K backend.
    variants: list[tuple[str, str | None]] = [
        ("2k", os.environ.get("GEMINI_SELFIE_IMAGE_SIZE", "2K")),
        ("compat", None),
        ("1k", "1K"),
    ]

    v229._log(
        "AI_SELFIE_V242_START stage=%s models=%s refs=%s retries=%s variants=%s",
        stage, ",".join(models), len(labeled_images), attempts_per_variant,
        ",".join(name for name, _ in variants),
    )

    limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, limits=limits) as client:
        for model in models:
            for variant_name, image_size in variants:
                parts: list[dict[str, Any]] = [{"text": prompt}]
                for label, data, mime in prepared:
                    parts.append({"text": label})
                    parts.append(v229._inline(data, mime))
                config: dict[str, Any] = {"responseModalities": ["TEXT", "IMAGE"]}
                if image_size:
                    config["imageConfig"] = {
                        "aspectRatio": base._aspect_ratio(),
                        "imageSize": image_size,
                    }
                payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}

                for attempt in range(1, attempts_per_variant + 1):
                    try:
                        v229._log(
                            "AI_SELFIE_V242_ATTEMPT stage=%s model=%s variant=%s attempt=%s/%s refs=%s",
                            stage, model, variant_name, attempt, attempts_per_variant, len(labeled_images),
                        )
                        response = await client.post(
                            f"{v229._base_url()}/models/{model}:generateContent",
                            headers=headers,
                            json=payload,
                        )
                        if response.status_code >= 400:
                            detail = response.text[:350].replace("\n", " ")
                            errors.append(f"{stage}/{model}/{variant_name}: HTTP {response.status_code}: {detail}")
                            v229._log(
                                "AI_SELFIE_V242_HTTP_ERROR stage=%s model=%s variant=%s attempt=%s status=%s body=%s",
                                stage, model, variant_name, attempt, response.status_code, detail,
                            )
                            if _retryable(response.status_code) and attempt < attempts_per_variant:
                                delay = min(20.0, (2.0 ** (attempt - 1)) * 2.5 + random.uniform(0.2, 1.2))
                                await asyncio.sleep(delay)
                                continue
                            break

                        output = extractor._extract_final_image(response.json())
                        if output and len(output) > 1024:
                            runtime = v229._runtime()
                            if runtime is not None:
                                runtime.AI_SELFIE_LAST_PROVIDER = "google_gemini_direct_resilient"
                                runtime.AI_SELFIE_LAST_MODEL = model
                                runtime.AI_SELFIE_LAST_IMAGE_SIZE = image_size or "compat"
                                runtime.AI_SELFIE_LAST_STAGE = stage
                            v229._log(
                                "AI_SELFIE_V242_SUCCESS stage=%s model=%s variant=%s attempt=%s refs=%s bytes=%s",
                                stage, model, variant_name, attempt, len(labeled_images), len(output),
                            )
                            return output, model

                        errors.append(f"{stage}/{model}/{variant_name}: response contained no final image")
                        v229._log(
                            "AI_SELFIE_V242_NO_IMAGE stage=%s model=%s variant=%s attempt=%s",
                            stage, model, variant_name, attempt,
                        )
                        if attempt < attempts_per_variant:
                            await asyncio.sleep(min(10.0, 1.5 * attempt))
                    except (httpx.TimeoutException, httpx.NetworkError) as exc:
                        errors.append(f"{stage}/{model}/{variant_name}: {type(exc).__name__}: {exc}")
                        v229._log(
                            "AI_SELFIE_V242_NETWORK_ERROR stage=%s model=%s variant=%s attempt=%s error=%r",
                            stage, model, variant_name, attempt, exc,
                        )
                        if attempt < attempts_per_variant:
                            await asyncio.sleep(min(20.0, 2.5 * (2 ** (attempt - 1))))
                            continue
                        break
                    except Exception as exc:
                        errors.append(f"{stage}/{model}/{variant_name}: {type(exc).__name__}: {exc}")
                        v229._log(
                            "AI_SELFIE_V242_EXCEPTION stage=%s model=%s variant=%s attempt=%s error=%r",
                            stage, model, variant_name, attempt, exc,
                        )
                        break

    compact = " | ".join(errors[-6:])
    raise RuntimeError("Google Gemini temporarily failed after resilient retries: " + compact)


def install() -> bool:
    global _INSTALLED, _ORIGINAL
    from neyrobot_prod import selfie_v229_canonical_two_stage as v229

    if _ORIGINAL is None:
        _ORIGINAL = v229._call_google
    v229._call_google = resilient_call_google

    # V238 resolves v229._call_google at execution time, so patching this one symbol
    # hardens the active terminal architecture without touching generation handlers.
    if not _INSTALLED:
        _INSTALLED = True
        print(f"[neyrobot-prod] V242 resilient Gemini caller installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "resilient_call_google", "install"]
