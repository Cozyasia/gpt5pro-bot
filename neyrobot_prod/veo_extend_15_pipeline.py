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


async def create_extended_video(*, directory, prompt, duration_seconds, base_url,
                                api_key, fast_model, poll, reference_image=None,
                                progress=None):
    """Chain Veo-native extensions, persisting each billed operation separately.

    Google limit: initial 8s plus up to twenty 7s extensions (148s).
    Only provider-native cumulative video is fed to the next extension.
    """
    if not isinstance(duration_seconds, int) or not 8 <= duration_seconds <= 148:
        raise ValueError("Veo Extend duration must be between 8 and 148 seconds")
    from math import ceil
    steps = ceil(max(0, duration_seconds - 8) / 7)
    if steps > 20:
        raise ValueError("Google Veo allows at most 20 extensions")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    journal = directory / "journal.json"

    async def submit():
        if progress:
            await progress("Генерирую исходные 8 секунд Veo")
        return await submit_veo_task(base_url, api_key, fast_model, prompt,
                                     reference_image=reference_image)

    async def save(index, payload):
        save_scene(directory, index, payload)

    original = read_job(journal)["scenes"].get("1", {})
    if original.get("state") != "completed":
        await run_journaled_scene(journal, 1, submit, poll, save)
    first = list_complete_scenes(directory, 1)[0]
    task_id = read_job(journal)["scenes"]["1"].get("task_id")
    if not task_id:
        raise RuntimeError("Original Veo task ID missing")

    final = directory / ("final_%ds.mp4" % duration_seconds)
    if final.is_file() and abs(probe_duration(final) - duration_seconds) < 0.25:
        return final

    # A provider-generated video must be passed directly; locally assembled
    # or trimmed videos are not eligible inputs for native Veo extension.
    source_uri = None
    latest = first
    for step in range(1, steps + 1):
        state_file = directory / ("extension_%02d.json" % step)
        video_file = directory / ("extension_%02d.mp4" % step)
        state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else None
        if state is None:
            if source_uri is None:
                source_uri = await _provider_uri(base_url, api_key, task_id)
            state = {"status": "submitting", "source_uri": source_uri, "step": step}
            write_job(state_file, state)
            if progress:
                await progress("Veo Extend: продление %d из %d" % (step, steps))
            try:
                uri, response = await extend_veo(
                    base_url, api_key, source_uri, _extension_prompt(prompt),
                    model=os.getenv("VEO_EXTEND_MODEL", "veo-3.1"))
                state = {"status": "accepted", "source_uri": source_uri,
                         "result_uri": uri, "response": response, "step": step}
                write_job(state_file, state)
            except BaseException:
                write_job(state_file, {"status": "uncertain",
                                       "source_uri": source_uri, "step": step})
                raise
        if state.get("status") != "accepted" or not state.get("result_uri"):
            raise RuntimeError("Extension %d needs provider reconciliation; no paid retry" % step)
        source_uri = state["result_uri"]
        if not video_file.is_file():
            await _download(source_uri, video_file)
        expected = 8 + 7 * step
        actual = probe_duration(video_file)
        if abs(actual - expected) > 0.5:
            raise RuntimeError(
                "Provider returned %.2fs at extension %d, expected %ds cumulative video. "
                "Stopping before further paid calls." % (actual, step, expected))
        latest = video_file

    import shutil
    import subprocess
    if steps == 0:
        latest = first
    actual = probe_duration(latest)
    if actual < duration_seconds - 0.25:
        raise RuntimeError("Provider output shorter than requested duration")
    if abs(actual - duration_seconds) <= 0.25:
        shutil.copyfile(latest, final)
    else:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
             "-y", "-i", str(latest), "-t", str(duration_seconds),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
             "-c:a", "aac", "-movflags", "+faststart", str(final)],
            capture_output=True, timeout=600)
        if result.returncode:
            raise RuntimeError("Final Veo trim failed: " +
                               result.stderr.decode("utf-8", "replace")[-300:])
    if abs(probe_duration(final) - duration_seconds) > 0.25:
        raise RuntimeError("Final video duration mismatch")
    return final


async def create_extended_15(**kwargs):
    """Compatibility entry point for existing Telegram 15-second jobs."""
    return await create_extended_video(duration_seconds=15, **kwargs)
