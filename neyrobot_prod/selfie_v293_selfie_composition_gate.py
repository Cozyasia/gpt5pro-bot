# -*- coding: utf-8 -*-
"""V293 strict selfie composition gate.

V292 fixed identity fidelity and hero-edge contamination. The remaining visible
failure mode is upstream composition: Gemini can still draw a long foreground arm
as if PERSON A were physically holding an invisible phone. That arm is already part
of the scene before identity transfer, so no face-swap or integration patch can fix
it afterwards.

V293 therefore tightens the selfie prompt and adds one inexpensive vision gate after
the existing V280 device/POV validator. It rejects elongated foreground limbs,
invisible-phone holding poses and overly loose selfie framing before identity work.
"""
from __future__ import annotations

import contextlib
import os
from typing import Any

from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v229_canonical_two_stage as v229

VERSION = "v293-selfie-anatomy-framing-gate-2026-08-17"
_INSTALLED = False
_ORIGINAL_PROMPT = terminal._prompt
_ORIGINAL_GOOGLE_CALL = v229._call_google


def _log(message: str, *args: Any) -> None:
    with contextlib.suppress(Exception):
        v229._log(message, *args)


def _is_selfie_prompt(text: str) -> bool:
    value = str(text or "").lower()
    return "shot mode: селфи" in value or "shot mode: selfie" in value or "selfie pov contract" in value or "front-camera" in value


def _prompt(name: str, scene_text: str, shot_label: str, has_scene_image: bool, attempt: int) -> str:
    text = _ORIGINAL_PROMPT(name, scene_text, shot_label, has_scene_image, attempt)
    label = str(shot_label or "").lower()
    if "селфи" not in label and "selfie" not in label:
        return text
    return text + (
        " SELFIE ANATOMY/FRAMING CONTRACT — NON-NEGOTIABLE: the phone camera is a virtual invisible viewpoint; "
        "neither PERSON A nor PERSON B needs to physically hold it. DO NOT draw a camera-holding arm, an arm reaching toward the lens, "
        "an oversized foreground forearm, a hand disappearing beyond the frame as if gripping an invisible phone, or any extreme wide-angle limb distortion. "
        "Both principal people must have normal human shoulder/arm proportions. An arm may rest naturally beside the body or around the companion, "
        "but it must not project toward the camera. Compose a believable close front-camera portrait, preferably shoulders-up or chest-up; "
        "do not show thighs/knees or a seated half-body composition when a normal close selfie is possible. Both principal faces must be clear, near-frontal, "
        "similar in apparent camera distance, unobstructed, and looking naturally into the same lens. If any foreground limb looks stretched, enlarged, malformed, "
        "or implies an invisible phone outside the frame, discard the draft and render another composition."
    )


async def _anatomy_gate(raw: bytes, *, stage: str) -> bool:
    import httpx

    key = v229._key()
    if not key:
        return True
    try:
        data, mime = v229._prepare(raw)
        model = str(os.getenv("GEMINI_SELFIE_VALIDATOR_MODEL") or "gemini-2.5-flash").strip()
        prompt = (
            "Judge ONLY whether this image is a production-quality close front-camera selfie. Return exactly PASS or FAIL. "
            "FAIL if either principal person has an arm/forearm stretched toward the lens, an oversized foreground limb, extreme perspective elongation, "
            "a hand or arm exiting the frame as though holding an invisible phone, malformed arm anatomy, or an implausibly long arm. "
            "FAIL if the framing is unnecessarily loose/half-body with thighs or knees visible instead of a normal shoulders-up/chest-up selfie. "
            "FAIL if one principal face is strongly obstructed, strongly turned away, or clearly not looking toward the camera. "
            "A normal arm around the companion or resting naturally at the side is allowed. PASS only if body anatomy, selfie perspective, close framing, "
            "and both principal faces all look immediately believable."
        )
        parts = [{"text": prompt}, v229._inline(data, mime)]
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["TEXT"], "temperature": 0.0},
        }
        headers = {"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
        timeout = httpx.Timeout(35.0, connect=12.0, read=35.0, write=25.0, pool=12.0)
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            response = await client.post(f"{v229._base_url()}/models/{model}:generateContent", headers=headers, json=payload)
        if response.status_code >= 400:
            _log("AI_SELFIE_V293_GATE stage=%s status=validator_unavailable http=%s body=%s", stage, response.status_code, response.text[:240])
            return True
        texts: list[str] = []
        for candidate in (response.json().get("candidates") or []):
            for part in ((candidate.get("content") or {}).get("parts") or []):
                if isinstance(part, dict) and part.get("text"):
                    texts.append(str(part["text"]))
        verdict = " ".join(texts).strip().upper()
        ok = verdict.startswith("PASS") and "FAIL" not in verdict[:20]
        _log("AI_SELFIE_V293_GATE stage=%s status=%s verdict=%s", stage, "pass" if ok else "reject", verdict[:100])
        return ok
    except Exception as exc:
        # Optional quality gate must not make the product unavailable on validator outage.
        _log("AI_SELFIE_V293_GATE stage=%s status=validator_exception error_type=%s error=%s", stage, type(exc).__name__, str(exc)[:350])
        return True


async def _call_google_with_anatomy_gate(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    output, model = await _ORIGINAL_GOOGLE_CALL(prompt, labeled_images, stage)
    if _is_selfie_prompt(prompt) and "scene_hero_body_attempt" in str(stage):
        if not await _anatomy_gate(output, stage=stage):
            raise ValueError("SELFIE_ANATOMY_POLICY_REJECTED: stretched foreground limb, invisible-phone pose, loose framing or camera-facing failure")
    return output, model


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    terminal._prompt = _prompt
    v229._call_google = _call_google_with_anatomy_gate
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V293"
    setattr(terminal, "_v293_selfie_anatomy_gate", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V293 selfie anatomy + close-framing gate installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
