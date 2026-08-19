# -*- coding: utf-8 -*-
"""V247: quality-only overlay on the proven V246 selfie runtime.

The V246 behavior is intentionally frozen. This overlay changes only the isolated
PERSON-A FaceSwap image path:
- the already-selected compact V245 target ROI is supersampled before Segmind/PiAPI;
- the provider therefore works with more target pixels while seeing the exact same
  face, expression, crop geometry and identity source;
- the provider result is then reduced once, with Lanczos, into the original ROI by
  V245's target-only merge;
- V246's synthetic 2x sharpen/downsample micro-detail pass is bypassed because it
  can emphasize provider compression blocks without creating real information.

No prompt, hero reference, scene composition, source-photo selection, callback,
payment, acknowledgement, duplicate guard or delivery behavior is changed.
There is no generative restoration, no source-texture injection and no redraw.
"""
from __future__ import annotations

import io
from typing import Any

VERSION = "v247-provider-supersample-detail-lock-2026-08-19"
_INSTALLED = False
_BASE_V246_ENFORCE = None


def _modules():
    from neyrobot_prod import selfie_v241_authoritative_runtime as v241
    from neyrobot_prod import selfie_v244_runtime_lock as v245
    from neyrobot_prod import selfie_v246_quality_hardlock as v246
    from neyrobot_prod import selfie_v233_true_face_transfer as transfer
    from neyrobot_prod import selfie_v229_canonical_two_stage as google
    from neyrobot_prod import selfie_v219_triref_scene_owner as ui
    return v241, v245, v246, transfer, google, ui


def _log(message: str, *args: Any) -> None:
    v241, _, _, _, _, _ = _modules()
    v241._log(message, *args)


def _provider_supersample_roi(image: bytes):
    """Keep V245 crop coordinates, only raise provider working resolution.

    Segmind returned the last successful 908x1033 ROI at only ~148 KB. The face
    itself was ~622 px wide, so provider compression is the remaining visible
    bottleneck. Feeding the identical ROI at a ~1440 px long side gives the real
    FaceSwap stage a supersampled target and lets the existing V245 merge perform
    one high-quality downsample back to native scene coordinates.
    """
    from PIL import Image

    _, v245, _, _, _, _ = _modules()
    raw, box = v245._compact_provider_roi(bytes(image or b""))
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    iw, ih = im.size
    long_side = max(iw, ih)

    target_long = 1440
    if long_side >= 1380:
        _log(
            "AI_SELFIE_V247_PROVIDER_INPUT supersample=false input=%sx%s output=%sx%s scale=1.000 box=%s,%s,%s,%s",
            iw, ih, iw, ih, box[0], box[1], box[2], box[3],
        )
        return raw, box

    scale = min(1.55, float(target_long) / max(1.0, float(long_side)))
    nw = max(iw, int(round(iw * scale)))
    nh = max(ih, int(round(ih * scale)))
    enlarged = im.resize((nw, nh), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    enlarged.save(out, format="JPEG", quality=100, subsampling=0, optimize=True)
    encoded = out.getvalue()
    _log(
        "AI_SELFIE_V247_PROVIDER_INPUT supersample=true input=%sx%s output=%sx%s scale=%.3f box=%s,%s,%s,%s jpeg=100 bytes=%s",
        iw, ih, nw, nh, scale, box[0], box[1], box[2], box[3], len(encoded),
    )
    return encoded, box


def _merge_supersampled_provider(base: bytes, swapped_crop: bytes, box):
    """One target-only downsample/merge; no invented detail and no source pixels."""
    _, v245, _, _, _, _ = _modules()
    from PIL import Image

    with Image.open(io.BytesIO(bytes(swapped_crop or b""))) as src:
        provider_w, provider_h = int(src.width), int(src.height)
    cw, ch = int(box[2] - box[0]), int(box[3] - box[1])

    merged = v245._merge_clean_face_roi(bytes(base), bytes(swapped_crop), box)
    _log(
        "AI_SELFIE_V247_MERGE provider=%sx%s native_roi=%sx%s supersample_downsample=%s v246_detail_bypassed=true source_pixels=false hero=pixel_locked",
        provider_w, provider_h, cw, ch, str((provider_w, provider_h) != (cw, ch)).lower(),
    )
    return merged


def enforce_runtime(bind_generate: bool = True) -> None:
    """Reassert V246 first, then replace only its two quality hooks."""
    global _BASE_V246_ENFORCE
    v241, v245, v246, transfer, google, ui = _modules()

    if _BASE_V246_ENFORCE is None:
        raise RuntimeError("V247 base V246 enforce function was not captured")

    _BASE_V246_ENFORCE(bind_generate=bind_generate)

    transfer._left_person_crop = _provider_supersample_roi
    transfer._merge_left_crop = _merge_supersampled_provider
    transfer._ensure_full_hd = v246._ensure_full_hd_lossless

    v246.enforce_runtime = enforce_runtime
    v241.enforce_runtime = lambda: enforce_runtime(bind_generate=True)

    for mod in (transfer, google, ui, v241, v245, v246):
        mod.VERSION = VERSION

    runtime = v241._runtime()
    if runtime is not None:
        runtime.CELEBRITY_SELFIE_VERSION = VERSION
        runtime.AI_SELFIE_RUNTIME_VERSION = VERSION
        runtime.SELFIE_STORAGE_VERSION = VERSION
        runtime.SELFIE_COMMANDS_VERSION = VERSION
        runtime.SELFIE_ADMIN_VERSION = VERSION
        runtime.CELEBRITY_SELFIE_ROUTE = "v247-v246-locked-front-camera-real-faceswap-provider-supersample-target-only-native2k"
        runtime.AI_SELFIE_PROVIDER = (
            "Gemini V242 expression lock -> V245 compact isolated target -> "
            "V247 provider-input supersample -> real Segmind/PiAPI FaceSwap -> "
            "single Lanczos target-only merge -> V246 lossless native-2K final"
        )
        runtime.AI_SELFIE_GENERATION_STAGES = 2

    _log(
        "AI_SELFIE_V247_ENFORCE status=ok base=v246 architecture_unchanged=true provider_input=supersampled<=1440 faceswap=real merge=single_lanczos_target_only source_texture=false redraw=false hero=pixel_locked version=%s",
        VERSION,
    )


def _install_v248_overlay() -> None:
    """Load historical provider layers, V251 owner, then final V252 quality overlay."""
    try:
        from neyrobot_prod.selfie_v248_faceswap_v4_quality import install as install_v248_quality
        install_v248_quality()
        from neyrobot_prod.selfie_v250_hyperswap_identity import install as install_v250_identity
        install_v250_identity()
        from neyrobot_prod.selfie_v251_v2_identity_detail import install as install_v251_identity
        install_v251_identity()
        from neyrobot_prod.selfie_v252_v3_png_quality import install as install_v252_quality
        install_v252_quality()
    except Exception as exc:
        _log("AI_SELFIE_V252_INSTALL status=failed error=%s:%s", type(exc).__name__, exc)


def install() -> None:
    global _INSTALLED, _BASE_V246_ENFORCE
    if _INSTALLED:
        enforce_runtime(bind_generate=True)
        _install_v248_overlay()
        return

    _, _, v246, _, _, _ = _modules()
    current = v246.enforce_runtime
    if current is enforce_runtime:
        _INSTALLED = True
        _install_v248_overlay()
        return
    _BASE_V246_ENFORCE = current
    v246.enforce_runtime = enforce_runtime
    enforce_runtime(bind_generate=True)
    _INSTALLED = True
    print("[neyrobot-prod] V247 provider supersample quality overlay installed over frozen V246", flush=True)
    _install_v248_overlay()


__all__ = ["VERSION", "install", "enforce_runtime"]
