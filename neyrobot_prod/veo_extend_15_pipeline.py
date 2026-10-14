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
from .veo_extend_comet import find_video_uri
from .veo_scene_runner import run_journaled_scene
from .veo_scene_artifacts import save_scene, list_complete_scenes, load_scene_uri
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


def _artifact_uri_file(video_file: Path) -> Path:
    return video_file.with_suffix(".uri")


def _load_artifact_uri(video_file: Path) -> str | None:
    uri_file = _artifact_uri_file(video_file)
    if not uri_file.is_file():
        return None
    value = uri_file.read_text(encoding="utf-8").strip()
    return value or None


def _save_artifact_uri(video_file: Path, result: bytes) -> None:
    uri = getattr(result, "provider_uri", None)
    uri_file = _artifact_uri_file(video_file)
    if isinstance(uri, str) and uri.strip():
        tmp = uri_file.with_suffix(".uri.tmp")
        tmp.write_text(uri.strip(), encoding="utf-8")
        os.replace(tmp, uri_file)
    elif uri_file.exists():
        uri_file.unlink()


def _render_delivery_video(source: Path, destination: Path, duration_seconds: int,
                           output_aspect_ratio: str) -> None:
    """Render the cumulative native result into the Telegram delivery shape.

    The Google Veo Fast Extend backend currently rejects a 9:16 source at the
    Extend boundary. Native generation therefore stays 16:9 for the entire
    cumulative chain; only the final, already-generated result is center-cropped
    to the user's requested 9:16 delivery format.
    """
    import subprocess

    if output_aspect_ratio == "9:16":
        video_filter = (
            "scale=720:1280:force_original_aspect_ratio=increase,"
            "crop=720:1280,setsar=1"
        )
    elif output_aspect_ratio == "16:9":
        video_filter = "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1"
    else:
        raise ValueError("Unsupported output aspect ratio")

    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
         "-i", str(source), "-t", str(duration_seconds), "-vf", video_filter,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
         str(destination)],
        capture_output=True, timeout=600,
    )
    if result.returncode:
        raise RuntimeError(
            "Final Veo aspect-ratio render failed: " +
            result.stderr.decode("utf-8", "replace")[-300:]
        )


async def create_extended_video(*, directory, prompt, duration_seconds, base_url,
                                api_key, fast_model, poll, reference_image=None,
                                progress=None, submit_initial=None,
                                extend_video=None, output_aspect_ratio=None):
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
        if submit_initial is not None:
            return await submit_initial()
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
    if (output_aspect_ratio is None and final.is_file() and
            abs(probe_duration(final) - duration_seconds) < 0.25):
        return final

    # A provider-generated cumulative video must be passed directly to the
    # native extension API. Local concatenation of independent scenes is not a
    # substitute for Extend.
    if steps and extend_video is None:
        raise RuntimeError(
            "No verified native Veo Extend provider is configured; "
            "set VEO_EXTEND_PROVIDER=google and GEMINI_VIDEO_API_KEY"
        )
    latest = first
    for step in range(1, steps + 1):
        state_file = directory / ("extension_%02d.json" % step)
        video_file = directory / ("extension_%02d.mp4" % step)
        state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else None
        # A confirmed 4xx validation refusal has no operation ID and therefore
        # no paid generation to recover. It may be retried on a later resume
        # after the payload/configuration is fixed. Uncertain states remain a
        # hard stop and are never resubmitted automatically.
        if state and state.get("status") == "rejected":
            state = None
        if state is None:
            state = {"status": "submitting", "source_artifact": latest.name, "step": step}
            write_job(state_file, state)
            if progress:
                await progress("Veo Extend: продление %d из %d" % (step, steps))
            try:
                # Google native extension requires the provider Video object
                # from the previous operation. The URI is persisted next to
                # every MP4; bytes remain a compatibility path for injected
                # test providers, while GoogleVeoClient rejects them before
                # any paid POST.
                source_uri = (
                    load_scene_uri(directory, 1)
                    if latest == first
                    else _load_artifact_uri(latest)
                )
                source = source_uri or latest.read_bytes()
                result = await extend_video(
                    source, _extension_prompt(prompt))
                if not isinstance(result, bytes) or len(result) < 1024:
                    raise RuntimeError("Native Veo Extend returned empty video bytes")
                _write_video_atomically(video_file, result)
                _save_artifact_uri(video_file, result)
                state = {"status": "accepted", "source_artifact": latest.name,
                         "result_artifact": video_file.name, "step": step}
                write_job(state_file, state)
            except Exception as exc:
                if exc.__class__.__name__ in {
                    "GoogleVeoSubmissionUncertain", "GoogleVeoPollUncertain", "UncertainExtension"
                }:
                    write_job(state_file, {"status": "uncertain",
                                           "source_artifact": latest.name, "step": step,
                                           "error": str(exc)[:500]})
                else:
                    write_job(state_file, {"status": "rejected",
                                           "source_artifact": latest.name, "step": step,
                                           "error": str(exc)[:500]})
                raise
        if state.get("status") != "accepted" or not state.get("result_artifact"):
            raise RuntimeError("Extension %d needs provider reconciliation; no paid retry" % step)
        if not video_file.is_file():
            raise RuntimeError(
                "Extension %d was accepted but its local result artifact is missing; "
                "manual provider reconciliation is required" % step
            )
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
    if output_aspect_ratio:
        _render_delivery_video(latest, final, duration_seconds, output_aspect_ratio)
    elif abs(actual - duration_seconds) <= 0.25:
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


def _write_video_atomically(destination: Path, payload: bytes) -> None:
    """Persist an accepted native result without exposing a partial MP4."""
    import tempfile
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".extension-", suffix=".mp4", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, destination)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


async def create_extended_15(**kwargs):
    """Compatibility entry point for existing Telegram 15-second jobs."""
    return await create_extended_video(duration_seconds=15, **kwargs)
