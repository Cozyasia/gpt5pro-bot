# engine.py
import os, httpx

COMET_API_KEY = os.getenv("COMET_API_KEY","")
SUNO_API_KEY = os.getenv("SUNO_API_KEY","")
MIDJOURNEY_API_KEY = os.getenv("MIDJOURNEY_API_KEY","")

async def sora2(prompt, seconds=10, size="720x1280"):
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post(
            "https://api.cometapi.com/v1/videos",
            headers={"Authorization": f"Bearer {COMET_API_KEY}"},
            data={"prompt": prompt, "model": "sora-2-all", "seconds": str(seconds), "size": size},
        )
        r.raise_for_status()
        return r.json()

async def suno(prompt):
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post(
            "https://api.suno.ai/v1/generate",
            headers={"Authorization": f"Bearer {SUNO_API_KEY}"},
            json={"prompt": prompt},
        )
        r.raise_for_status()
        return r.json()

async def midjourney(prompt):
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post(
            "https://api.cometapi.com/mj/submit/imagine",
            headers={"Authorization": f"Bearer {MIDJOURNEY_API_KEY}"},
            json={"prompt": prompt, "base64Array": []},
        )
        r.raise_for_status()
        return r.json()
