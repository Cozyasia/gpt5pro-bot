# -*- coding: utf-8 -*-
"""Production AI Selfie fidelity patch.

V279 goals:
1) keep bounded-latency Gemini + InSwapper production flow;
2) preserve the user's SOURCE portrait expression/face geometry instead of inheriting
   the synthetic Gemini target expression;
3) use the PhotoRoom opaque full-head compositor by default when configured;
4) keep a safe InSwapper-only fallback when PhotoRoom is unavailable.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal

VERSION = "v279-source-expression-lock-2026-08-16"
_ORIGINAL_PROMPT = terminal._prompt
_INSTALLED = False


def _prompt(name: str, scene_text: str, shot_label: str, has_scene_image: bool, attempt: int) -> str:
    base = _ORIGINAL_PROMPT(name, scene_text, shot_label, has_scene_image, attempt)
    is_selfie = "селфи" in str(shot_label or "").lower() or "selfie" in str(shot_label or "").lower()
    if is_selfie:
        camera_rule = (
            " SELFIE CAMERA GEOMETRY — ABSOLUTE REQUIREMENT: the requested image is the FINAL FRAME already captured by the front-facing smartphone camera. "
            "The viewpoint is the phone/front-camera lens itself, not an external camera looking at someone taking a selfie. "
            "NO PHONE OR CAMERA DEVICE MAY APPEAR ANYWHERE IN THE IMAGE. Do not show a smartphone, phone edge, phone back, camera body, selfie stick, mirror reflection of a phone, or a hand/arm holding a phone toward the camera. "
            "Both people look naturally toward the invisible front-camera lens. A forearm may enter frame only if anatomically natural and NOT holding any device. "
            "Treat any visible phone/camera/selfie-stick as a composition failure and regenerate without it."
        )
    else:
        camera_rule = (
            " THIRD-PERSON CAMERA GEOMETRY — ABSOLUTE REQUIREMENT: this is an ordinary photograph taken by another person. "
            "Neither principal person is taking a selfie. NO smartphone, camera body, selfie stick, or hand holding a recording device may appear in-frame."
        )

    # This does not ask Gemini to invent the final face. It makes the temporary
    # Person-A head pose compatible with the SOURCE portrait so the terminal opaque
    # source-head transplant can preserve the user's real expression without warp.
    expression_rule = (
        " PERSON A SOURCE-EXPRESSION LOCK: keep Person A's head nearly frontal, with only a small natural yaw/pitch, and keep the mouth/eyes in a neutral relaxed configuration compatible with the supplied user portrait. "
        "Do NOT invent a smile, open mouth, squint, raised eyebrow, grimace, or dramatic facial expression for Person A. "
        "The generated Person-A face is TEMPORARY geometry only: final identity, facial expression, eyelids, mouth shape, cheeks, jaw details, hairline and facial texture will be taken from the user's portrait source. "
        "Therefore preserve a source-compatible head angle and do not stylize or beautify Person A's face."
    )
    return base + camera_rule + expression_rule


def _exact_identity_enabled() -> bool:
    # V279 changes the production default to ON. This is the only path that can
    # preserve the SOURCE portrait's actual expression; InSwapper transfers identity
    # but normally keeps the TARGET expression. It can still be explicitly disabled.
    value = str(os.getenv("AI_SELFIE_V279_SOURCE_EXPRESSION_LOCK") or os.getenv("AI_SELFIE_V277_EXACT_IDENTITY_CORE") or "1").strip().lower()
    return value not in {"0", "false", "off", "no"}


def _has_photoroom() -> bool:
    return bool((os.getenv("PHOTOROOM_API_KEY") or os.getenv("PHOTO_ROOM_API_KEY") or "").strip())


async def _identity_swap(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, str]:
    """Identity transfer plus optional exact SOURCE-expression head ownership."""
    raw: bytes | None = None
    provider = ""

    replicate_token = str(os.getenv("REPLICATE_API_TOKEN") or "").strip()
    if replicate_token:
        try:
            from neyrobot_prod import selfie_v252_faceswap_quality_diag as ins

            provider_target = terminal._supersample(target_crop, min_long_side=1400)
            provider_source = terminal._supersample(source_crop, min_long_side=1400)
            inputs = {
                "upscale": 2,
                "source_img": ins._data_url(provider_source),
                "target_img": ins._data_url(provider_target),
                "face_restore": False,
                "face_upsample": True,
                "source_indexes": "0",
                "target_indexes": "0",
                "background_enhance": False,
                "codeformer_fidelity": 1.0,
            }
            log(
                "AI_SELFIE_V279_IDENTITY trace=%s provider=replicate_inswapper stage=create "
                "target_native=%s target_provider=%s source_native=%s source_provider=%s "
                "upscale=2 face_restore=false face_upsample=true indexes=0 timeout=120s source_expression_lock=%s",
                trace, fs.dims(target_crop), fs.dims(provider_target), fs.dims(source_crop), fs.dims(provider_source),
                str(_exact_identity_enabled()).lower(),
            )
            candidate = await asyncio.wait_for(
                ins._replicate_swap_once(
                    version=ins.REPLICATE_INSWAPPER_VERSION,
                    inputs=inputs,
                    trace=trace,
                    label="v279_prod_inswapper_source_expression",
                ),
                timeout=120.0,
            )
            if len(candidate) >= 1024 and fs.sha(candidate) != fs.sha(provider_target):
                raw = candidate
                provider = "replicate_inswapper_fast_fidelity"
                log(
                    "AI_SELFIE_V279_IDENTITY trace=%s provider=replicate_inswapper stage=success sha=%s dims=%s bytes=%s",
                    trace, fs.sha(raw), fs.dims(raw), len(raw),
                )
            else:
                raise RuntimeError("InSwapper returned unchanged/empty target")
        except asyncio.TimeoutError:
            log("AI_SELFIE_V279_IDENTITY trace=%s provider=replicate_inswapper stage=timeout budget=120s fallback=piapi", trace)
        except Exception as exc:
            log(
                "AI_SELFIE_V279_IDENTITY trace=%s provider=replicate_inswapper stage=fallback error_type=%s error=%s",
                trace, type(exc).__name__, str(exc)[:700],
            )

    if raw is None and str(os.getenv("PIAPI_API_KEY") or "").strip():
        provider_target = terminal._supersample(target_crop, min_long_side=1250)
        provider_source = terminal._supersample(source_crop, min_long_side=1250)
        candidate = await fs.piapi_swap_once(provider_target, provider_source, log, trace=trace)
        if fs.sha(candidate) == fs.sha(provider_target):
            raise RuntimeError("PiAPI returned unchanged target crop")
        raw = candidate
        provider = "piapi_qubico_fast_fallback"

    if raw is None:
        raise RuntimeError("No Face Swap provider configured or identity providers timed out")

    # Critical V279 stage: replace the generated/target expression with the actual
    # SOURCE head. PhotoRoom provides the real hair/head silhouette; the compositor
    # owns the entire interior opaquely and blends only a narrow boundary ring.
    if _exact_identity_enabled():
        if not _has_photoroom():
            log(
                "AI_SELFIE_V279_IDENTITY trace=%s stage=source_expression_lock status=unavailable reason=photoroom_key_missing fallback=%s",
                trace, provider,
            )
        else:
            try:
                from neyrobot_prod import selfie_v272_photoroom_head_cutout_diag as v276

                source_face = fs.source_face_crop(source_crop, None)
                target_face = fs.source_face_crop(raw, None)
                exact, meta = v276._overlay(
                    source_full_raw=source_crop,
                    source_face_box=source_face.face_box,
                    target_full_raw=raw,
                    target_face_box=target_face.face_box,
                    baseline_full_raw=raw,
                    outer_strength=0.98,
                    core_strength=1.0,
                )
                if len(exact) >= 1024 and fs.sha(exact) != fs.sha(raw):
                    log(
                        "AI_SELFIE_V279_IDENTITY trace=%s stage=source_expression_lock status=success "
                        "provider=%s sha=%s dims=%s mode=%s ownership=source_head_opaque expression=source_portrait",
                        trace, provider, fs.sha(exact), fs.dims(exact), meta.get("mode"),
                    )
                    return exact, provider + "+source_expression_lock"
                raise RuntimeError("source-expression overlay returned unchanged output")
            except Exception as exc:
                log(
                    "AI_SELFIE_V279_IDENTITY trace=%s stage=source_expression_lock status=fallback "
                    "provider=%s error_type=%s error=%s",
                    trace, provider, type(exc).__name__, str(exc)[:700],
                )

    return raw, provider


def install() -> bool:
    global _INSTALLED
    if _INSTALLED and getattr(terminal, "_v279_source_expression_lock", False):
        return True
    terminal._prompt = _prompt
    terminal._identity_swap = _identity_swap
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V279"
    setattr(terminal, "_v279_source_expression_lock", True)

    try:
        from neyrobot_prod import selfie_v218_runtime_owner as owner
        owner.VERSION = VERSION
    except Exception:
        pass

    print(f"[neyrobot-prod] V279 source expression lock installed version={VERSION}", flush=True)
    _INSTALLED = True
    return True


__all__ = ["VERSION", "install"]
