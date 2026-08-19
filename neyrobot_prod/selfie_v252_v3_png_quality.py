# -*- coding: utf-8 -*-
"""V252: quality-only FaceSwap overlay over the stable V251 runtime.

Why this exists:
- V251 restored identity fidelity with the older V2 route, but V2 still returns a
  visibly compressed/soft face and the source-frequency repair can create doubled
  eye/nose/lip edges when source and target geometry differ by only a few pixels.
- V252 does NOT change callbacks, UX, scene prompts, hero isolation, photo #3
  authority, target ROI, merge geometry, delivery, payment, or native 2K handling.
- It changes only the provider call used for PERSON A.

Provider path:
- verified close-up crop from photo #3;
- Segmind FaceSwap V3;
- RetinaFace detection;
- Lanczos interpolation;
- PNG output at quality 100;
- low CodeFormer weight (0.25) to avoid smoothing/re-synthesising identity;
- NO source-pixel/frequency injection after the provider;
- V250 face-local merge and V246 lossless final remain unchanged.

If V3 fails, the existing PiAPI fallback in the frozen transfer path remains active.
"""
from __future__ import annotations

import io
from typing import Any

VERSION = "v252-v3-png-quality-lock-2026-08-20"
_INSTALLED = False
_BASE_V251_ENFORCE = None
_BASE_TRUE_FACE_TRANSFER = None


def _modules():
    from neyrobot_prod import selfie_v241_authoritative_runtime as v241
    from neyrobot_prod import selfie_v244_runtime_lock as v245
    from neyrobot_prod import selfie_v246_quality_hardlock as v246
    from neyrobot_prod import selfie_v247_provider_supersample as v247
    from neyrobot_prod import selfie_v248_faceswap_v4_quality as v249
    from neyrobot_prod import selfie_v250_hyperswap_identity as v250
    from neyrobot_prod import selfie_v251_v2_identity_detail as v251
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    from neyrobot_prod import selfie_v219_triref_scene_owner as ui
    return v241, v245, v246, v247, v249, v250, v251, transfer, google, ui


def _log(message: str, *args: Any) -> None:
    v241, *_ = _modules()
    v241._log(message, *args)


def _dims(data: bytes) -> tuple[int, int]:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(bytes(data or b""))) as im:
            return int(im.width), int(im.height)
    except Exception:
        return 0, 0


async def _segmind_v3_png(
    target_img: bytes,
    source_face: bytes,
    target_index: int = 0,
    source_index: int = 0,
) -> bytes | None:
    """Run FaceSwap V3 with explicit lossless/high-quality controls.

    No post-provider source-detail overlay is allowed here. The V3 result is merged
    as returned so we do not create ghosted high-frequency features.
    """
    v241, _, _, _, _, _, v251, _, _, _ = _modules()
    runtime = v241._runtime()
    if runtime is None or not getattr(runtime, "SEGMIND_API_KEY", ""):
        return None

    try:
        source_crop = v251._verified_source_face(bytes(source_face or b""))
    except Exception as exc:
        _log("AI_SELFIE_V252_SOURCE status=failed reason=%s:%s", type(exc).__name__, str(exc)[:180])
        return None

    tw, th = _dims(target_img)
    sw, sh = _dims(source_crop)
    url = f"{runtime.SEGMIND_BASE_URL}/v1/faceswap-v3"
    payload = {
        "source_img": runtime._b64_for_faceswap(source_crop),
        "target_img": runtime._b64_for_faceswap(bytes(target_img or b"")),
        "input_faces_index": str(int(target_index)),
        "source_faces_index": str(int(source_index)),
        "face_restore": "codeformer-v0.1.0.pth",
        "face_restore_weight": 0.25,
        "interpolation": "Lanczos",
        "detection_face_order": "large-small",
        "facedetection": "retinaface_resnet50",
        "detect_gender_input": "no",
        "detect_gender_source": "no",
        "image_format": "png",
        "image_quality": 100,
        "base64": False,
    }
    headers = {
        "x-api-key": runtime.SEGMIND_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json,image/*",
    }

    _log(
        "AI_SELFIE_V252_PROVIDER_START provider=segmind_faceswap_v3 target=%sx%s source=%sx%s format=png quality=100 interpolation=Lanczos restore=codeformer weight=0.25 source_detail=false",
        tw, th, sw, sh,
    )
    try:
        timeout_s = max(90.0, float(getattr(runtime, "FACESWAP_TIMEOUT_S", 180) or 180))
        async with runtime.httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                _log(
                    "AI_SELFIE_V252_PROVIDER status=failed reason=http_%s body=%s fallback=piapi",
                    response.status_code,
                    (response.text or "")[:400].replace("\n", " "),
                )
                return None
            image = await runtime._extract_image_bytes_from_json_or_response(response, client)
            if not image:
                _log("AI_SELFIE_V252_PROVIDER status=failed reason=no_output fallback=piapi")
                return None
            image = bytes(image)
            ow, oh = _dims(image)
            runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = "segmind_faceswap_v3_png_v252"
            _log(
                "AI_SELFIE_V252_PROVIDER_SUCCESS provider=segmind_faceswap_v3 output=%sx%s bytes=%s content_type=%s post_detail=false",
                ow, oh, len(image), response.headers.get("content-type", ""),
            )
            return image
    except Exception as exc:
        _log("AI_SELFIE_V252_PROVIDER status=failed reason=%s:%s fallback=piapi", type(exc).__name__, str(exc)[:240])
        return None


async def _true_face_transfer_with_v252_label(runtime: Any, stage1: bytes, source: bytes, source_photo_no: int):
    global _BASE_TRUE_FACE_TRANSFER
    if not callable(_BASE_TRUE_FACE_TRANSFER):
        raise RuntimeError("V252 base true-face-transfer function is unavailable")

    runtime.AI_SELFIE_LAST_FACESWAP_PROVIDER = ""
    final, legacy_provider = await _BASE_TRUE_FACE_TRANSFER(runtime, stage1, source, source_photo_no)
    actual = str(getattr(runtime, "AI_SELFIE_LAST_FACESWAP_PROVIDER", "") or "")
    provider = "segmind_faceswap_v3_png_verified_source_isolated" if actual == "segmind_faceswap_v3_png_v252" else str(legacy_provider or "")
    _log(
        "AI_SELFIE_V252_TRANSFER_RESULT provider=%s legacy_provider=%s actual_marker=%s",
        provider, legacy_provider, actual or "none",
    )
    return final, provider


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert V251 architecture, then replace only provider quality behavior."""
    global _BASE_V251_ENFORCE
    v241, v245, v246, v247, v249, v250, v251, transfer, google, ui = _modules()
    if not callable(_BASE_V251_ENFORCE):
        raise RuntimeError("V252 base V251 enforcer was not captured")

    _BASE_V251_ENFORCE(bind_generate=bind_generate)

    runtime = v241._runtime()
    if runtime is not None:
        runtime._segmind_faceswap_v2 = _segmind_v3_png

    # Keep all proven V251/V247 geometry and delivery. Only disable V251's
    # source-frequency postprocess by bypassing its provider function entirely.
    transfer._left_person_crop = v247._provider_supersample_roi
    transfer._merge_left_crop = v250._merge_face_local
    transfer._ensure_full_hd = v246._ensure_full_hd_lossless
    transfer._true_face_transfer = _true_face_transfer_with_v252_label

    # The existing V251 generation owner is intentionally retained. Repoint its
    # late-bound enforcer to V252 instead of registering yet another callback.
    v251.enforce_runtime = enforce_runtime
    v246.enforce_runtime = enforce_runtime
    v247.enforce_runtime = enforce_runtime
    v241.enforce_runtime = lambda: enforce_runtime(bind_generate=True)

    for mod in (transfer, google, ui, v241, v245, v246, v247, v249, v250, v251):
        mod.VERSION = VERSION

    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v252-front-camera-v3-png-verified-source-supersampled-face-local-native2k"
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini V242 expression lock -> V247 supersampled isolated PERSON-A ROI -> "
            "verified photo-3 face -> Segmind FaceSwap V3 PNG100/Lanczos/RetinaFace/CodeFormer0.25 -> "
            "no source-detail injection -> V250 face-local merge -> V246 lossless native-2K final; PiAPI fallback"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V252_ENFORCE status=ok base=v251 provider=segmind_faceswap_v3 format=png quality=100 interpolation=Lanczos restore_weight=0.25 source_detail=false merge=face_local owner=v251_reused hero=pixel_locked version=%s",
        VERSION,
    )


def install() -> None:
    global _INSTALLED, _BASE_V251_ENFORCE, _BASE_TRUE_FACE_TRANSFER
    _, _, _, _, _, _, v251, transfer, _, _ = _modules()
    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        return

    current = v251.enforce_runtime
    if current is enforce_runtime:
        _INSTALLED = True
        return
    _BASE_V251_ENFORCE = current

    base_transfer = getattr(v251, "_BASE_TRUE_FACE_TRANSFER", None)
    if not callable(base_transfer):
        base_transfer = getattr(transfer, "_true_face_transfer", None)
    _BASE_TRUE_FACE_TRANSFER = base_transfer

    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V252 V3 PNG quality overlay installed over stable V251 owner", flush=True)


__all__ = ["VERSION", "install", "enforce_runtime"]
