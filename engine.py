
"""
engine.py
Unified AI Engine Router for Video & Image Generation
Supports: SORA 2, SUNA, MidJourney, Runway, Kling, Luma
"""

import os
import time
import httpx
from typing import Dict, Any

# =====================
# ENV CONFIG
# =====================
SORA2_API_KEY = os.getenv("SORA2_API_KEY", "")
SUNA_API_KEY = os.getenv("SUNA_API_KEY", "")
MIDJOURNEY_API_KEY = os.getenv("MIDJOURNEY_API_KEY", "")
RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY", "")
KLING_API_KEY = os.getenv("KLING_API_KEY", "")
LUMA_API_KEY = os.getenv("LUMA_API_KEY", "")

TIMEOUT = float(os.getenv("ENGINE_TIMEOUT", "120"))


class EngineError(Exception):
    pass


# =====================
# CORE ROUTER
# =====================
async def run_engine(engine: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    engine = engine.lower().strip()

    if engine == "sora2":
        return await sora2_video(payload)
    if engine == "suna":
        return await suna_video(payload)
    if engine == "midjourney":
        return await midjourney_image(payload)
    if engine == "runway":
        return await runway_video(payload)
    if engine == "kling":
        return await kling_video(payload)
    if engine == "luma":
        return await luma_video(payload)

    raise EngineError(f"Unknown engine: {engine}")


# =====================
# ENGINE IMPLEMENTATIONS
# =====================
async def sora2_video(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not SORA2_API_KEY:
        raise EngineError("SORA2_API_KEY is missing")

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            "https://api.sora.ai/v2/video",
            headers={"Authorization": f"Bearer {SORA2_API_KEY}"},
            json=payload,
        )
    r.raise_for_status()
    return r.json()


async def suna_video(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not SUNA_API_KEY:
        raise EngineError("SUNA_API_KEY is missing")

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            "https://api.suna.ai/v1/video",
            headers={"Authorization": f"Bearer {SUNA_API_KEY}"},
            json=payload,
        )
    r.raise_for_status()
    return r.json()


async def midjourney_image(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not MIDJOURNEY_API_KEY:
        raise EngineError("MIDJOURNEY_API_KEY is missing")

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            "https://api.midjourney.com/v1/imagine",
            headers={"Authorization": f"Bearer {MIDJOURNEY_API_KEY}"},
            json=payload,
        )
    r.raise_for_status()
    return r.json()


async def runway_video(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not RUNWAY_API_KEY:
        raise EngineError("RUNWAY_API_KEY is missing")

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            "https://api.runwayml.com/v1/image_to_video",
            headers={"Authorization": f"Bearer {RUNWAY_API_KEY}"},
            json=payload,
        )
    r.raise_for_status()
    return r.json()


async def kling_video(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not KLING_API_KEY:
        raise EngineError("KLING_API_KEY is missing")

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            "https://api.kling.ai/v1/video",
            headers={"Authorization": f"Bearer {KLING_API_KEY}"},
            json=payload,
        )
    r.raise_for_status()
    return r.json()


async def luma_video(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not LUMA_API_KEY:
        raise EngineError("LUMA_API_KEY is missing")

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            "https://api.lumalabs.ai/dream-machine/v1/video",
            headers={"Authorization": f"Bearer {LUMA_API_KEY}"},
            json=payload,
        )
    r.raise_for_status()
    return r.json()
