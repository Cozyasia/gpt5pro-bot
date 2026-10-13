"""Durable 8+7 second Veo extension workflow. No automatic retry of paid POSTs."""
from __future__ import annotations
import fcntl
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .veo_comet_adapter import submit_veo_task
from .veo_extend_comet import extend_veo, find_video_uri
from .veo_scene_runner import run_journaled_scene
from .veo_scene_artifacts import save_scene, list_complete_scenes
from .veo_task_journal import read_job, write_job
from .veo_assembler import probe_duration


def _uri_from_provider(payload):
    """Only provider-reported video URI; never synthesize one from task ID."""
    if not isinstance(payload, (dict, list)):
        return None
    return find_video_uri(payload)


def _extension_prompt(original):
    return (
        "Extend the supplied Veo video forward by exactly 7 seconds, preserving the "
        "same presenter, face, clothes, framing, environment, camera motion, lighting, "
        "voice timbre and native audio continuity. All speech must be Russian; no "
        "English words or English narration. Continue the action and dialogue "
        "naturally, without restarting the scene. Original creative brief: " + original
    )


async def _provider_uri(base, key, task_id):
    """Read-only status queries cannot create new billed tasks."""
    async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
        for route in ("/v1/videos/", "/v1/tasks/"):
            try:
                resp = await client.get(base.rstrip("/") + route + task_id,
                                        headers={"Authorization": "Bearer " + key})
                if resp.status_code != 200:
                    continue
                data = resp.json()
                uri = _uri_from_provider(data)
                if uri:
                    return uri
            except (httpx.RequestError, ValueError):
                continue
    raise RuntimeError("Provider did not expose original Veo video URI. Extension not submitted; no second charge.")


async def _download(url, destination):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Provider video download requires HTTPS")
    tmp = destination.with_suffix(".download")
    async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with open(tmp, "wb") as out:
                async for chunk in response.aiter_bytes():
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
    if tmp.stat().st_size < 1024:
        raise ValueError("Provider returned empty video")
    os.replace(tmp, destination)


def _assemble(first, extended, destination):
    """An extension may contain the entire 15s timeline or only the additional 7s."""
    import subprocess
    duration = probe_duration(extended)
    if 14.5 <= duration <= 16:
        os.replace(extended, destination)
        return destination
    if not 6.5 <= duration <= 8.5:
        raise RuntimeError("Unexpected Veo extension duration; original files preserved")
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
         "-i", str(first), "-i", str(extended),
         "-filter_complex",
         "[0:v]fps=24,scale=720:1280,setsar=1,trim=duration=8,setpts=PTS-STARTPTS[v0];"
         "[1:v]fps=24,scale=720:1280,setsar=1,trim=duration=7,setpts=PTS-STARTPTS[v1];"
         "[0:a]aresample=48000,atrim=duration=8,asetpts=PTS-STARTPTS[a0];"
         "[1:a]aresample=48000,atrim=duration=7,asetpts=PTS-STARTPTS[a1];"
         "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]",
         "-map", "[v]", "-map", "[a]", "-t", "15", "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "128k",
         "-movflags", "+faststart", str(destination)],
        capture_output=True, timeout=600)
    if proc.returncode:
        raise RuntimeError("FFmpeg failed: " + proc.stderr.decode("utf-8", "replace")[-300:])
    if abs(probe_duration(destination) - 15) > 0.2:
        raise RuntimeError("15s output duration validation failed")
    return destination


async def create_extended_15(*, directory, prompt, base_url, api_key, fast_model,
                             poll, reference_image=None, progress=None):
    """Caller supplies existing read-only task polling and holds a per-job lock."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    journal = directory / "journal.json"
    async def submit():
        if progress:
            await progress("Генерирую первые 8 секунд Veo")
        return await submit_veo_task(base_url, api_key, fast_model, prompt,
                                     reference_image=reference_image)
    async def save(index, payload):
        save_scene(directory, index, payload)
    first_record = read_job(journal)["scenes"].get("1", {})
    if first_record.get("state") != "completed":
        await run_journaled_scene(journal, 1, submit, poll, save)
    clips = list_complete_scenes(directory, 1)
    if not clips:
        raise RuntimeError("Original 8s video missing; never resubmit completed task")
    first = clips[0]
    task_id = read_job(journal)["scenes"]["1"].get("task_id")
    if not task_id:
        raise RuntimeError("Original task ID missing; extension blocked")
    output = directory / "final_15s.mp4"
    if output.is_file() and abs(probe_duration(output) - 15) < 0.2:
        return output
    extension_file = directory / "extension.mp4"
    state_file = directory / "extension.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else None
    if state is None:
        source_uri = await _provider_uri(base_url, api_key, task_id)
        state = {"status": "submitting", "source_uri": source_uri}
        write_job(state_file, state)
        if progress:
            await progress("Продлеваю исходный ролик на 7 секунд через Veo Extend")
        try:
            uri, response = await extend_veo(
                base_url, api_key, source_uri, _extension_prompt(prompt),
                model=os.getenv("VEO_EXTEND_MODEL", "veo-3.1"))
            state = {"status": "accepted", "source_uri": source_uri,
                     "result_uri": uri, "response": response}
            write_job(state_file, state)
        except BaseException:
            write_job(state_file, {"status": "uncertain", "source_uri": source_uri})
            raise
    if not extension_file.is_file():
        uri = state.get("result_uri")
        if not uri:
            raise RuntimeError("Extension submitted without a final video URI. Manual reconciliation required; no retry.")
        await _download(uri, extension_file)
    return _assemble(first, extension_file, output)
