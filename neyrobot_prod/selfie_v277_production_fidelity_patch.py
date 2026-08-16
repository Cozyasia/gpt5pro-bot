# -*- coding: utf-8 -*-
"""Production AI Selfie fidelity patch.

V280 goals:
1) one universal path for every user: Gemini composition -> deterministic selfie-policy
   validation -> InSwapper identity -> source-native facial-expression core;
2) reject third-person "person taking a selfie" compositions and any visible phone,
   camera or selfie stick before Face Swap;
3) preserve the user's real eyes/mouth/expression from photo #3 without routing the
   facial interior through a second generative/restoration pass;
4) keep native source pixels whenever possible and avoid the soft/pixelated whole-head
   PhotoRoom transplant as the production default;
5) keep bounded latency and safe provider fallbacks.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
from io import BytesIO
from typing import Any

from neyrobot_prod import face_swap_service_v257 as fs
from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v229_canonical_two_stage as v229

VERSION = "v280-universal-selfie-pov-source-core-2026-08-16"
_ORIGINAL_PROMPT = terminal._prompt
_ORIGINAL_GOOGLE_CALL = v229._call_google
_INSTALLED = False


def _is_selfie_prompt(text: str) -> bool:
    value = str(text or "").lower()
    return "selfie camera geometry" in value or "shot mode: селфи" in value or "shot mode: selfie" in value


def _prompt(name: str, scene_text: str, shot_label: str, has_scene_image: bool, attempt: int) -> str:
    base = _ORIGINAL_PROMPT(name, scene_text, shot_label, has_scene_image, attempt)
    is_selfie = "селфи" in str(shot_label or "").lower() or "selfie" in str(shot_label or "").lower()
    if is_selfie:
        camera_rule = (
            " SELFIE POV CONTRACT — NON-NEGOTIABLE: output the FINAL IMAGE FROM THE FRONT-FACING PHONE CAMERA ITSELF. "
            "The camera IS the invisible phone lens. This must NOT be a photograph of people taking a selfie. "
            "NO PHONE, PHONE EDGE, PHONE BACK, CAMERA, ACTION CAMERA, SELFIE STICK OR MIRROR-REFLECTED DEVICE may be visible anywhere. "
            "NO arm or hand may terminate in or grip a device. Do not place an oversized forearm toward a visible phone. "
            "Use a natural front-camera composition: the two principal people are close to the lens, typically chest-up or shoulders-up, and look toward the lens. "
            "If your draft contains any device or an external-camera view of a selfie being taken, DISCARD that draft and render a genuine device-free front-camera POV instead."
        )
    else:
        camera_rule = (
            " THIRD-PERSON CAMERA CONTRACT — NON-NEGOTIABLE: this is an ordinary photograph taken by another person. "
            "Neither principal person is taking a selfie. NO phone, camera body, selfie stick, mirror-reflected device, or hand holding a recording device may appear in-frame."
        )

    expression_rule = (
        " PERSON A SOURCE-EXPRESSION LOCK: keep Person A's head near-frontal or mild three-quarter and compatible with the supplied user portrait. "
        "Do NOT invent a smile, open mouth, squint, raised eyebrow, grimace, beauty retouching or dramatic expression for Person A. "
        "The generated Person-A face is temporary geometry only. Final facial identity, eyes, eyelids, mouth shape and expression are taken from user portrait photo #3."
    )
    return base + camera_rule + expression_rule


async def _selfie_policy_check(raw: bytes, log: Any, *, stage: str) -> bool:
    """Cheap vision gate. A failed gate makes the existing composition loop regenerate."""
    import httpx

    key = v229._key()
    if not key:
        return True
    try:
        data, mime = v229._prepare(raw)
        model = str(os.getenv("GEMINI_SELFIE_VALIDATOR_MODEL") or "gemini-2.5-flash").strip()
        prompt = (
            "Inspect this generated image for a production SELFIE POV contract. Return exactly PASS or FAIL. "
            "FAIL if ANY smartphone, phone edge/back, camera, selfie stick, mirror-reflected recording device is visible; "
            "FAIL if a principal person's hand/arm is visibly holding a device; FAIL if the image is an external/third-person view of somebody taking a selfie. "
            "PASS only when the image itself plausibly is the final front-camera frame and no recording device is visible."
        )
        parts = [{"text": prompt}, v229._inline(data, mime)]
        payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": {"responseModalities": ["TEXT"], "temperature": 0.0}}
        headers = {"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
        timeout = httpx.Timeout(45.0, connect=15.0, read=45.0, write=30.0, pool=15.0)
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            response = await client.post(f"{v229._base_url()}/models/{model}:generateContent", headers=headers, json=payload)
        if response.status_code >= 400:
            log("AI_SELFIE_V280_POLICY stage=%s status=validator_unavailable http=%s body=%s", stage, response.status_code, response.text[:300])
            return True
        texts: list[str] = []
        for candidate in (response.json().get("candidates") or []):
            for part in ((candidate.get("content") or {}).get("parts") or []):
                if isinstance(part, dict) and part.get("text"):
                    texts.append(str(part["text"]))
        verdict = " ".join(texts).strip().upper()
        ok = verdict.startswith("PASS") and "FAIL" not in verdict[:20]
        log("AI_SELFIE_V280_POLICY stage=%s status=%s verdict=%s", stage, "pass" if ok else "reject", verdict[:120])
        return ok
    except Exception as exc:
        # Do not make the whole product unavailable because the low-cost validator had a transient error.
        log("AI_SELFIE_V280_POLICY stage=%s status=validator_exception error_type=%s error=%s", stage, type(exc).__name__, str(exc)[:400])
        return True


async def _call_google_with_policy(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    output, model = await _ORIGINAL_GOOGLE_CALL(prompt, labeled_images, stage)
    if _is_selfie_prompt(prompt) and "scene_hero_body_attempt" in str(stage):
        if not await _selfie_policy_check(output, v229._log, stage=stage):
            raise ValueError("SELFIE_POV_POLICY_REJECTED: visible device or external third-person selfie viewpoint")
    return output, model


def _exact_identity_enabled() -> bool:
    value = str(os.getenv("AI_SELFIE_V280_SOURCE_FACE_CORE") or os.getenv("AI_SELFIE_V279_SOURCE_EXPRESSION_LOCK") or "1").strip().lower()
    return value not in {"0", "false", "off", "no"}


def _source_native_face_core(source_crop: bytes, baseline_raw: bytes, log: Any, *, trace: str) -> tuple[bytes, dict[str, Any]]:
    """Put source facial pixels over the swapped target with an opaque inner core.

    This intentionally does not use PhotoRoom, CodeFormer, Gemini or another Face Swap
    for the final facial interior. Hair/body/lighting remain owned by the already-swapped
    target; the identity-critical eyes/nose/mouth/cheeks come directly from photo #3.
    """
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

    src = fs.image(source_crop).convert("RGB")
    dst = fs.image(baseline_raw).convert("RGB")
    source_face = fs.source_face_crop(source_crop, None)
    target_face = fs.source_face_crop(baseline_raw, None)
    sx, sy, sw, sh = [float(v) for v in source_face.face_box]
    tx, ty, tw, th = [float(v) for v in target_face.face_box]

    # Production quality gate is geometry-based, not user-specific. If a source portrait
    # is truly tiny we keep InSwapper rather than magnifying a low-resolution face core.
    if sw < 300 or sh < 300:
        raise ValueError(f"source portrait face too small for source-native core: {int(sw)}x{int(sh)}")

    # Work on a compact target facial region. Slight forehead/jaw margin preserves the
    # user's expression and facial proportions while leaving hair silhouette to target.
    left = max(0, int(round(tx - tw * 0.10)))
    top = max(0, int(round(ty - th * 0.16)))
    right = min(dst.width, int(round(tx + tw * 1.10)))
    bottom = min(dst.height, int(round(ty + th * 1.08)))
    pw, ph = right - left, bottom - top
    if pw < 96 or ph < 96:
        raise ValueError("target facial core region is too small")

    scale_x = sw / max(tw, 1.0)
    scale_y = sh / max(th, 1.0)
    c = sx + (left - tx) * scale_x
    f = sy + (top - ty) * scale_y
    affine = getattr(getattr(Image, "Transform", Image), "AFFINE", getattr(Image, "AFFINE", 0))
    resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    warped = src.transform((pw, ph), affine, (scale_x, 0.0, c, 0.0, scale_y, f), resample=resample, fillcolor=(0, 0, 0))

    # Preserve texture. Only compensate modestly for local contrast lost during affine
    # resampling; no face restoration/generation is performed here.
    warped = ImageEnhance.Sharpness(warped).enhance(1.10)

    mask = Image.new("L", (pw, ph), 0)
    draw = ImageDraw.Draw(mask)
    mx = max(4, int(round(pw * 0.055)))
    my_top = max(3, int(round(ph * 0.035)))
    my_bottom = max(5, int(round(ph * 0.060)))
    draw.ellipse((mx, my_top, pw - mx, ph - my_bottom), fill=255)
    # Extremely narrow feather: identity/expression pixels stay opaque over almost all face.
    blur = max(1.2, min(pw, ph) * 0.010)
    soft = mask.filter(ImageFilter.GaussianBlur(blur))
    core = mask.filter(ImageFilter.MinFilter(5 if min(pw, ph) >= 220 else 3))
    # Restore the inner source-owned area to fully opaque after feathering.
    import numpy as np
    a = np.asarray(soft, dtype=np.uint8)
    ccore = np.asarray(core, dtype=np.uint8)
    a[ccore >= 250] = 255
    mask = Image.fromarray(a, "L")

    ref = dst.crop((left, top, right, bottom))
    merged = Image.composite(warped, ref, mask)
    out = dst.copy()
    out.paste(merged, (left, top))
    payload = fs.jpeg(out, max_side=2200, quality=100)
    meta = {
        "mode": "v280_source_native_face_core",
        "source_face_px": (int(sw), int(sh)),
        "target_face_px": (int(tw), int(th)),
        "patch": (left, top, right, bottom),
        "source_owned_core": True,
        "generative_restore_after_core": False,
    }
    log(
        "AI_SELFIE_V280_IDENTITY trace=%s stage=source_native_face_core source_face=%sx%s target_face=%sx%s patch=%s dims=%s",
        trace, int(sw), int(sh), int(tw), int(th), meta["patch"], fs.dims(payload),
    )
    return payload, meta


async def _identity_swap(target_crop: bytes, source_crop: bytes, log: Any, *, trace: str) -> tuple[bytes, str]:
    """High-quality identity transfer, then source-native expression/detail core."""
    raw: bytes | None = None
    provider = ""

    replicate_token = str(os.getenv("REPLICATE_API_TOKEN") or "").strip()
    if replicate_token:
        try:
            from neyrobot_prod import selfie_v252_faceswap_quality_diag as ins

            # Use the proven FullHD path universally. 1800px/4x costs more than V278,
            # but removes the recurring soft/pixelated face regression for new users.
            provider_target = terminal._supersample(target_crop, min_long_side=1800)
            provider_source = terminal._supersample(source_crop, min_long_side=1800)
            inputs = {
                "upscale": 4,
                "source_img": ins._data_url(provider_source),
                "target_img": ins._data_url(provider_target),
                "face_restore": True,
                "face_upsample": True,
                "source_indexes": "0",
                "target_indexes": "0",
                "background_enhance": False,
                "codeformer_fidelity": 0.95,
            }
            log(
                "AI_SELFIE_V280_IDENTITY trace=%s provider=replicate_inswapper stage=create target_native=%s target_provider=%s source_native=%s source_provider=%s upscale=4 face_restore=true face_upsample=true fidelity=0.95 timeout=180s",
                trace, fs.dims(target_crop), fs.dims(provider_target), fs.dims(source_crop), fs.dims(provider_source),
            )
            candidate = await asyncio.wait_for(
                ins._replicate_swap_once(version=ins.REPLICATE_INSWAPPER_VERSION, inputs=inputs, trace=trace, label="v280_prod_inswapper_fullhd_universal"),
                timeout=180.0,
            )
            if len(candidate) >= 1024 and fs.sha(candidate) != fs.sha(provider_target):
                raw = candidate
                provider = "replicate_inswapper_fullhd_restore95"
                log("AI_SELFIE_V280_IDENTITY trace=%s provider=replicate_inswapper stage=success sha=%s dims=%s bytes=%s", trace, fs.sha(raw), fs.dims(raw), len(raw))
            else:
                raise RuntimeError("InSwapper returned unchanged/empty target")
        except asyncio.TimeoutError:
            log("AI_SELFIE_V280_IDENTITY trace=%s provider=replicate_inswapper stage=timeout budget=180s fallback=piapi", trace)
        except Exception as exc:
            log("AI_SELFIE_V280_IDENTITY trace=%s provider=replicate_inswapper stage=fallback error_type=%s error=%s", trace, type(exc).__name__, str(exc)[:700])

    if raw is None and str(os.getenv("PIAPI_API_KEY") or "").strip():
        provider_target = terminal._supersample(target_crop, min_long_side=1600)
        provider_source = terminal._supersample(source_crop, min_long_side=1600)
        candidate = await fs.piapi_swap_once(provider_target, provider_source, log, trace=trace)
        if fs.sha(candidate) == fs.sha(provider_target):
            raise RuntimeError("PiAPI returned unchanged target crop")
        raw = candidate
        provider = "piapi_qubico_fullhd_fallback"

    if raw is None:
        raise RuntimeError("No Face Swap provider configured or identity providers timed out")

    if _exact_identity_enabled():
        try:
            exact, meta = _source_native_face_core(source_crop, raw, log, trace=trace)
            if len(exact) >= 1024 and fs.sha(exact) != fs.sha(raw):
                log(
                    "AI_SELFIE_V280_IDENTITY trace=%s stage=source_expression_lock status=success provider=%s sha=%s dims=%s mode=%s expression=source_photo3 native_core=true",
                    trace, provider, fs.sha(exact), fs.dims(exact), meta.get("mode"),
                )
                return exact, provider + "+source_native_face_core"
        except Exception as exc:
            log(
                "AI_SELFIE_V280_IDENTITY trace=%s stage=source_expression_lock status=fallback provider=%s error_type=%s error=%s",
                trace, provider, type(exc).__name__, str(exc)[:700],
            )

    return raw, provider


def install() -> bool:
    global _INSTALLED
    if _INSTALLED and getattr(terminal, "_v280_universal_selfie_fidelity", False):
        return True
    terminal._prompt = _prompt
    terminal._identity_swap = _identity_swap
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V280"
    # Wrap only the composition provider call. The validator fires only for selfie
    # composition stages and leaves all unrelated Gemini traffic unchanged.
    v229._call_google = _call_google_with_policy
    setattr(terminal, "_v280_universal_selfie_fidelity", True)

    try:
        from neyrobot_prod import selfie_v218_runtime_owner as owner
        owner.VERSION = VERSION
    except Exception:
        pass

    print(f"[neyrobot-prod] V280 universal selfie POV + source-native face core installed version={VERSION}", flush=True)
    _INSTALLED = True
    return True


__all__ = ["VERSION", "install"]
