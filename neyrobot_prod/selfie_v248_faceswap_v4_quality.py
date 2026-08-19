# -*- coding: utf-8 -*-
"""V248: provider-only quality overlay on the frozen V247/V246 selfie chain.

This module deliberately does NOT change selfie UX, callbacks, scene composition,
source-photo selection, front-camera framing, hero protection, ROI geometry, merge
geometry, generation locks, delivery, or the lossless final pass.

The only production experiment is the FaceSwap provider itself:
- keep the proven isolated PERSON-A target ROI from V247/V245;
- call Segmind FaceSwap v4 in quality mode;
- force face-only swap (never a head swap) and PNG quality 100;
- preserve the existing V247 single-Lanczos target-only merge;
- fall back to the exact previous V2 provider on any V4 error/no-output.

The frozen V247 snapshot is kept separately, so this overlay is fully reversible.
"""
from __future__ import annotations

import io
from typing import Any

VERSION = "v248-face-only-v4-quality-lock-2026-08-19"
_INSTALLED = False
_BASE_V247_ENFORCE = None
_BASE_PROVIDER = None


def _modules():
    from neyrobot_prod import selfie_v241_authoritative_runtime as v241
    from neyrobot_prod import selfie_v244_runtime_lock as v245
    from neyrobot_prod import selfie_v246_quality_hardlock as v246
    from neyrobot_prod import selfie_v247_provider_supersample as v247
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    from neyrobot_prod import selfie_v219_triref_scene_owner as ui
    return v241, v245, v246, v247, transfer, google, ui


def _log(message: str, *args: Any) -> None:
    v241, _, _, _, _, _, _ = _modules()
    v241._log(message, *args)


def _dims(data: bytes) -> tuple[int, int]:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(bytes(data or b""))) as im:
            return int(im.width), int(im.height)
    except Exception:
        return 0, 0


async def _segmind_faceswap_v4_face_quality(
    target_img: bytes,
    source_face: bytes,
    target_index: int = 0,
    source_index: int = 0,
) -> bytes | None:
    """Use V4 quality/face-only for the isolated PERSON-A ROI; V2 is hard fallback.

    Indices are accepted for signature compatibility. They are intentionally not
    sent to V4 because the target has already been isolated to PERSON-A by the
    proven V245/V247 path and the source is the authoritative photo-3 face.
    """
    global _BASE_PROVIDER

    v241, _, _, _, _, _, _ = _modules()
    runtime = v241._runtime()
    if runtime is None or not getattr(runtime, "SEGMIND_API_KEY", ""):
        if _BASE_PROVIDER is not None:
            return await _BASE_PROVIDER(target_img, source_face, target_index, source_index)
        return None

    url = f"{runtime.SEGMIND_BASE_URL}/v1/faceswap-v4"
    payload = {
        "source_image": runtime._b64_for_faceswap(bytes(source_face or b"")),
        "target_image": runtime._b64_for_faceswap(bytes(target_img or b"")),
        "model_type": "quality",
        "swap_type": "face",
        "style_type": "normal",
        "seed": 42,
        "image_format": "png",
        "image_quality": 100,
        "hardware": "fast",
        "base64": False,
    }
    headers = {
        "x-api-key": runtime.SEGMIND_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json,image/*",
    }

    tw, th = _dims(target_img)
    sw, sh = _dims(source_face)
    _log(
        "AI_SELFIE_V248_PROVIDER_START provider=segmind_faceswap_v4 mode=quality swap=face format=png quality=100 target=%sx%s source=%sx%s",
        tw, th, sw, sh,
    )

    try:
        timeout_s = float(getattr(runtime, "FACESWAP_TIMEOUT_S", 180) or 180)
        async with runtime.httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                _log(
                    "AI_SELFIE_V248_PROVIDER status=fallback_v2 reason=http_%s body=%s",
                    response.status_code,
                    (response.text or "")[:400].replace("\n", " "),
                )
                if _BASE_PROVIDER is not None:
                    return await _BASE_PROVIDER(target_img, source_face, target_index, source_index)
                return None

            image = await runtime._extract_image_bytes_from_json_or_response(response, client)
            if not image:
                _log("AI_SELFIE_V248_PROVIDER status=fallback_v2 reason=no_output")
                if _BASE_PROVIDER is not None:
                    return await _BASE_PROVIDER(target_img, source_face, target_index, source_index)
                return None

            image = bytes(image)
            ow, oh = _dims(image)
            _log(
                "AI_SELFIE_V248_PROVIDER_SUCCESS provider=segmind_faceswap_v4 output=%sx%s bytes=%s content_type=%s fallback=false",
                ow, oh, len(image), response.headers.get("content-type", ""),
            )
            # Do not run the legacy normalizer here. V247 already caps the target
            # working ROI and performs exactly one high-quality merge/downsample.
            # Returning the PNG bytes intact avoids another provider-output encode.
            return image
    except Exception as exc:
        _log(
            "AI_SELFIE_V248_PROVIDER status=fallback_v2 reason=%s:%s",
            type(exc).__name__, str(exc)[:240],
        )
        if _BASE_PROVIDER is not None:
            return await _BASE_PROVIDER(target_img, source_face, target_index, source_index)
        return None


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert the frozen V247 chain, then replace only the provider call."""
    global _BASE_V247_ENFORCE

    v241, v245, v246, v247, transfer, google, ui = _modules()
    if _BASE_V247_ENFORCE is None:
        raise RuntimeError("V248 base V247 enforce function was not captured")

    _BASE_V247_ENFORCE(bind_generate=bind_generate)

    runtime = v241._runtime()
    if runtime is not None:
        runtime._segmind_faceswap_v2 = _segmind_faceswap_v4_face_quality

    # Keep V248 as the final owner after old enforcers rebound themselves.
    v247.enforce_runtime = enforce_runtime
    v246.enforce_runtime = enforce_runtime
    v241.enforce_runtime = lambda: enforce_runtime(bind_generate=True)

    for mod in (transfer, google, ui, v241, v245, v246, v247):
        mod.VERSION = VERSION

    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v248-v247-v246-front-camera-face-only-v4-quality-real-faceswap-target-only-native2k"
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini V242 expression lock -> V245 compact isolated PERSON-A -> "
            "V247 provider supersample -> Segmind FaceSwap v4 quality face-only PNG -> "
            "V247 single-Lanczos target-only merge -> V246 lossless native-2K final; "
            "V2 fallback on provider failure"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V248_ENFORCE status=ok base=v247 architecture_unchanged=true provider=segmind_faceswap_v4 model_type=quality swap_type=face png=100 fallback=v2 source=photo3 hero=pixel_locked final_recompress=false version=%s",
        VERSION,
    )


def install() -> None:
    global _INSTALLED, _BASE_V247_ENFORCE, _BASE_PROVIDER

    v241, _, _, v247, _, _, _ = _modules()
    runtime = v241._runtime()

    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        return

    current = v247.enforce_runtime
    if current is enforce_runtime:
        _INSTALLED = True
        return

    _BASE_V247_ENFORCE = current
    if runtime is not None:
        existing = getattr(runtime, "_segmind_faceswap_v2", None)
        if existing is not _segmind_faceswap_v4_face_quality:
            _BASE_PROVIDER = existing

    v247.enforce_runtime = enforce_runtime
    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V248 face-only Segmind v4 quality overlay installed over frozen V247/V246", flush=True)


__all__ = ["VERSION", "install", "enforce_runtime"]
