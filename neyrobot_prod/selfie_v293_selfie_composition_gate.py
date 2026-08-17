# -*- coding: utf-8 -*-
"""V297 selfie composition gate.

The previous V293 validator treated a loose/wide selfie as a hard generation failure.
That was counterproductive because V284 already has a deterministic two-face crop
that can reframe a wide composition without another generative call. Rejecting the
wide frame here caused two or three expensive Gemini retries and turned a usable
composition into a multi-minute timeout.

V297 therefore keeps only the failures that cannot be repaired downstream:
- visible/implicit phone-holding anatomy;
- stretched or malformed foreground limbs;
- a principal face strongly obstructed or turned away.

Camera distance is now enforced strongly in the generation prompt, but a merely
wide result is accepted and handed to V284 for deterministic close reframing.
"""
from __future__ import annotations

import contextlib
import os
from typing import Any

from neyrobot_prod import selfie_v257_consolidated_runtime as terminal
from neyrobot_prod import selfie_v229_canonical_two_stage as v229

VERSION = "v297-selfie-close-prompt-no-distance-regeneration-2026-08-17"
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
        " V297 TRUE ARM-LENGTH SELFIE CONTRACT — ABSOLUTE: render the frame as if a normal phone front camera were held at ordinary arm length, approximately 45-75 cm from the two principal faces. "
        "This is NOT an event portrait and NOT an establishing shot. The two faces are the dominant visual subject and together fill most of the upper frame. "
        "Use shoulders-up or upper-chest-up framing. Each principal face should be roughly 20-30% of total image height, with the two heads close together at approximately the same camera distance. "
        "Do not show knees, thighs, full torsos, large empty floor/ceiling/background areas, or a distant view of the venue. The venue is only background context behind the faces. "
        "The virtual phone/camera itself is invisible. DO NOT draw a phone, camera, selfie stick, camera-holding arm, arm reaching toward the lens, oversized foreground forearm, or a hand disappearing beyond frame as if gripping a device. "
        "Both people must have normal shoulder/arm proportions, unobstructed near-frontal faces, and look naturally toward the same front-camera lens."
    )


async def _anatomy_gate(raw: bytes, *, stage: str) -> bool:
    """Reject only defects that deterministic reframing cannot repair.

    IMPORTANT: camera distance / loose framing is deliberately NOT a rejection reason.
    V284 owns deterministic close reframing after generation.
    """
    import httpx

    key = v229._key()
    if not key:
        return True
    try:
        data, mime = v229._prepare(raw)
        model = str(os.getenv("GEMINI_SELFIE_VALIDATOR_MODEL") or "gemini-2.5-flash").strip()
        prompt = (
            "Judge ONLY whether this generated image has an UNREPAIRABLE selfie anatomy/face defect. Return exactly PASS or FAIL. "
            "FAIL if either principal person has an arm/forearm stretched toward the lens, an oversized foreground limb, extreme perspective elongation, "
            "a hand or arm exiting the frame as though holding an invisible phone, malformed arm anatomy, or an implausibly long arm. "
            "FAIL if a principal face is strongly obstructed or strongly turned away so later identity transfer cannot work. "
            "DO NOT FAIL merely because the people are too far away, the framing is too wide, too much background is visible, or more torso is visible than desired; "
            "those distance/framing problems are corrected deterministically after this check. "
            "A normal arm around the companion or resting naturally at the side is allowed. PASS whenever anatomy and both usable face orientations are believable."
        )
        parts = [{"text": prompt}, v229._inline(data, mime)]
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["TEXT"], "temperature": 0.0},
        }
        headers = {"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
        timeout = httpx.Timeout(25.0, connect=10.0, read=25.0, write=20.0, pool=10.0)
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            response = await client.post(f"{v229._base_url()}/models/{model}:generateContent", headers=headers, json=payload)
        if response.status_code >= 400:
            _log("AI_SELFIE_V297_GATE stage=%s status=validator_unavailable http=%s body=%s", stage, response.status_code, response.text[:240])
            return True
        texts: list[str] = []
        for candidate in (response.json().get("candidates") or []):
            for part in ((candidate.get("content") or {}).get("parts") or []):
                if isinstance(part, dict) and part.get("text"):
                    texts.append(str(part["text"]))
        verdict = " ".join(texts).strip().upper()
        ok = verdict.startswith("PASS") and "FAIL" not in verdict[:20]
        _log("AI_SELFIE_V297_GATE stage=%s status=%s verdict=%s distance_reject=false", stage, "pass" if ok else "reject", verdict[:100])
        return ok
    except Exception as exc:
        _log("AI_SELFIE_V297_GATE stage=%s status=validator_exception error_type=%s error=%s", stage, type(exc).__name__, str(exc)[:350])
        return True


async def _call_google_with_anatomy_gate(prompt: str, labeled_images: list[tuple[str, bytes]], stage: str) -> tuple[bytes, str]:
    output, model = await _ORIGINAL_GOOGLE_CALL(prompt, labeled_images, stage)
    if _is_selfie_prompt(prompt) and "scene_hero_body_attempt" in str(stage):
        if not await _anatomy_gate(output, stage=stage):
            raise ValueError("SELFIE_ANATOMY_POLICY_REJECTED: unrecoverable limb anatomy or face orientation")
    return output, model


def install() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    terminal._prompt = _prompt
    v229._call_google = _call_google_with_anatomy_gate
    terminal.VERSION = VERSION
    terminal.TRACE_PREFIX = "AI_SELFIE_V297"
    setattr(terminal, "_v293_selfie_anatomy_gate", True)
    setattr(terminal, "_v297_distance_reject_disabled", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V297 selfie close prompt + no-distance-regeneration installed version={VERSION}", flush=True)
    return True


__all__ = ["VERSION", "install"]
