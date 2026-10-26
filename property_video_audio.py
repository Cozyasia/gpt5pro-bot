"""Scene-aware music and narration for property walkthroughs."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Awaitable, Callable


log = logging.getLogger(__name__)

SOUND_MODES = {"none", "music", "voice", "both"}
CAPTION_MODES = {"none", "narration", "custom"}
VOICE_MAP = {"male": "onyx", "female": "nova"}
LUXURY_LOUNGE_BRIEF = (
    "Entire track must be instrumental with no vocals. Elegant luxury real-estate lounge music, "
    "calm tropical atmosphere, warm modern electronic textures, soft piano, restrained deep-house "
    "rhythm, premium villa presentation, smooth continuous arrangement, no dramatic drops, no "
    "aggressive bass, no spoken words, no singing."
)


class PropertyAudioError(RuntimeError):
    """A safe property-audio failure."""


def validate_sound_mode(value: str | None) -> str:
    mode = str(value or "none").strip().lower()
    if mode not in SOUND_MODES:
        raise ValueError("Unsupported property-video sound mode")
    return mode


def sound_has_music(mode: str) -> bool:
    return validate_sound_mode(mode) in {"music", "both"}


def sound_has_voice(mode: str) -> bool:
    return validate_sound_mode(mode) in {"voice", "both"}


def validate_caption_mode(value: str | None) -> str:
    mode = str(value or "none").strip().lower()
    if mode not in CAPTION_MODES:
        raise ValueError("Unsupported property-video caption mode")
    return mode


def property_caption_segments(
    mode: str, scenes, *, narration_plan: dict | None = None,
    custom_lines: list[str] | None = None,
) -> list[tuple[float, float, str]]:
    """Return scene-timed captions without inventing property facts."""
    mode = validate_caption_mode(mode)
    if mode == "none":
        return []
    if mode == "narration":
        items = list((narration_plan or {}).get("segments") or [])
        if len(items) != len(scenes):
            raise PropertyAudioError("Narration captions do not match the scene plan")
        captions = []
        for scene, item in zip(scenes, items):
            start = float(item.get("start", 0))
            duration = float(scene.output_seconds)
            text = " ".join(str(item.get("text") or "").split())
            if not text:
                raise PropertyAudioError("Narration caption is empty")
            captions.append((start, start + duration, text))
        return captions
    lines = [" ".join(str(line).split()) for line in (custom_lines or []) if str(line).strip()]
    if len(lines) != len(scenes):
        raise PropertyAudioError(f"Custom captions require exactly {len(scenes)} lines")
    if any(len(line) > 68 for line in lines):
        raise PropertyAudioError("Each custom caption must be 68 characters or shorter")
    captions = []
    start = 0.0
    for scene, line in zip(scenes, lines):
        end = start + float(scene.output_seconds)
        captions.append((start, end, line))
        start = end
    return captions


def render_property_captions(
    source_path: str, output_path: str, captions: list[tuple[float, float, str]],
) -> str:
    """Burn readable Russian/English captions into the final property MP4."""
    if not captions:
        raise PropertyAudioError("No property captions to render")
    from neyrobot_prod.ad_video_safe_delivery import render_russian_overlay

    font_path = os.getenv(
        "PROPERTY_VIDEO_CAPTION_FONT_PATH",
        os.getenv("AD_CAPTION_FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    )
    return render_russian_overlay(
        source_path, output_path, captions, font_path,
        timeout=int(os.getenv("PROPERTY_VIDEO_FFMPEG_TIMEOUT_S", "600")),
        background=True,
        text_color="white",
        max_chars=28,
        max_lines=3,
        y_ratio=0.78,
    )


def narration_word_budgets(scenes) -> list[int]:
    return [max(4, int(max(1.0, float(scene.output_seconds) - 0.6) * 2.0)) for scene in scenes]


def _clean_segment(text: str, budget: int) -> str:
    words = " ".join(str(text or "").replace("\n", " ").split()).split()
    value = " ".join(words[:max(1, int(budget))]).strip()
    if value and value[-1] not in ".!?":
        value += "."
    return value


def parse_narration_plan(value: str | dict | None, scenes, language: str, voice: str) -> dict | None:
    if isinstance(value, dict):
        raw = value
    else:
        match = re.search(r"\{.*\}", str(value or ""), re.S)
        if not match:
            return None
        try:
            raw = json.loads(match.group(0))
        except (TypeError, ValueError):
            return None
    items = raw.get("scenes") if isinstance(raw, dict) else None
    if not isinstance(items, list) or len(items) != len(scenes):
        return None
    budgets = narration_word_budgets(scenes)
    segments = []
    for index, (item, budget) in enumerate(zip(items, budgets)):
        text = item.get("text") if isinstance(item, dict) else item
        cleaned = _clean_segment(str(text or ""), budget)
        if not cleaned:
            return None
        segments.append({
            "scene": index + 1,
            "start": round(sum(float(s.output_seconds) for s in scenes[:index]), 3),
            "duration": float(scenes[index].output_seconds),
            "text": cleaned,
        })
    return {
        "language": "en" if str(language).lower() == "en" else "ru",
        "voice": voice if voice in VOICE_MAP else "female",
        "segments": segments,
        "full_text": " ".join(item["text"] for item in segments),
    }


def _analysis_item(analysis: list[dict], index: int | None) -> dict:
    if index is None or index < 0 or index >= len(analysis):
        return {"space": "unknown", "summary": ""}
    item = analysis[index] if isinstance(analysis[index], dict) else {}
    return {
        "space": str(item.get("space") or "unknown"),
        "summary": " ".join(str(item.get("summary") or "").split())[:220],
    }


def _fallback_narration(analysis: list[dict], scenes, language: str, voice: str) -> dict:
    ru = {
        "exterior": "В кадре показана внешняя часть объекта",
        "entrance": "В кадре показана входная зона объекта",
        "living_room": "В кадре показана гостиная",
        "dining_room": "В кадре показана обеденная зона",
        "kitchen": "В кадре показана кухня",
        "bedroom": "В кадре показана спальня",
        "bathroom": "В кадре показана ванная комната",
        "terrace_pool": "В кадре показана терраса или открытая зона объекта",
        "corridor": "В кадре показана проходная зона объекта",
        "other": "Продолжаем обзор объекта недвижимости",
        "unknown": "Продолжаем обзор объекта недвижимости",
    }
    en = {
        "exterior": "The exterior part of the property is shown",
        "entrance": "The entrance area of the property is shown",
        "living_room": "The living room is shown",
        "dining_room": "The dining area is shown",
        "kitchen": "The kitchen is shown",
        "bedroom": "The bedroom is shown",
        "bathroom": "The bathroom is shown",
        "terrace_pool": "A terrace or outdoor area of the property is shown",
        "corridor": "A passage area of the property is shown",
        "other": "The property tour continues",
        "unknown": "The property tour continues",
    }
    table = en if str(language).lower() == "en" else ru
    unknown_lines = (
        [
            "We begin the property tour",
            "We continue through the next area",
            "We take a closer look at the interior",
            "We finish with the final property view",
        ]
        if str(language).lower() == "en"
        else [
            "Начинаем обзор объекта недвижимости",
            "Переходим к следующей части объекта",
            "Рассматриваем детали внутреннего пространства",
            "Завершаем обзор финальным видом объекта",
        ]
    )
    budgets = narration_word_budgets(scenes)
    items = []
    for index, scene in enumerate(scenes):
        reference_index = scene.photo_index if index == 0 else (
            scene.next_photo_index if scene.next_photo_index is not None else scene.photo_index
        )
        item = _analysis_item(analysis, reference_index)
        text = table.get(item["space"], table["unknown"])
        if item["space"] in {"other", "unknown"}:
            text = unknown_lines[index % len(unknown_lines)]
        items.append({"text": text})
    result = parse_narration_plan({"scenes": items}, scenes, language, voice) or {
        "language": language, "voice": voice, "segments": [], "full_text": "",
    }
    if analysis and all(_analysis_item(analysis, index)["space"] == "unknown" for index in range(len(analysis))):
        result["analysis_warning"] = (
            "Не удалось распознать помещения на фотографиях. Проверьте текст диктора перед запуском."
            if str(language).lower() != "en"
            else "The rooms could not be recognized. Review the narration before generation."
        )
    return result


async def _property_json_request(prompt: str, extra_system: str) -> str:
    """Use OpenAI first and the configured Comet gateway as a failover."""
    import httpx
    import main as production_main

    primary_key = str(
        getattr(production_main, "OPENAI_TTS_KEY", "")
        or getattr(production_main, "OPENAI_API_KEY", "")
        or ""
    ).strip()
    comet_key = str(getattr(production_main, "COMET_API_KEY", "") or "").strip()
    if not (primary_key or comet_key):
        raise PropertyAudioError("OpenAI key for property narration is unavailable")
    endpoints = []
    if primary_key:
        endpoints.append((
            str(getattr(production_main, "OPENAI_TTS_BASE_URL", "") or "https://api.openai.com/v1").rstrip("/"),
            primary_key,
            os.getenv("PROPERTY_VIDEO_TEXT_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
            "openai",
        ))
    if comet_key:
        endpoints.append((
            str(getattr(production_main, "COMET_BASE_URL", "") or "https://api.cometapi.com").rstrip("/"),
            comet_key,
            os.getenv("PROPERTY_VIDEO_COMET_TEXT_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
            "comet",
        ))
    last_error = None
    async with httpx.AsyncClient(timeout=90.0) as client:
        for base, key, model, provider in endpoints:
            try:
                response = await client.post(
                    f"{base}/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "temperature": 0.2,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": extra_system},
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
                response.raise_for_status()
                payload = response.json()
                return str(payload["choices"][0]["message"]["content"] or "")
            except Exception as exc:
                last_error = exc
                log.warning("PROPERTY_VIDEO_TEXT_PROVIDER_FAILED provider=%s", provider, exc_info=True)
    raise PropertyAudioError("Property narration providers are unavailable") from last_error


def _comet_tts_bytes_sync(text: str, voice: str) -> bytes | None:
    """Generate speech through Comet's OpenAI-compatible audio endpoint."""
    import httpx
    import main as production_main

    key = str(getattr(production_main, "COMET_API_KEY", "") or "").strip()
    base = str(getattr(production_main, "COMET_BASE_URL", "") or "https://api.cometapi.com").rstrip("/")
    if not key:
        return None
    models = list(dict.fromkeys(filter(None, [
        os.getenv("PROPERTY_VIDEO_COMET_TTS_MODEL", "gpt-4o-mini-tts").strip(),
        "tts-1-hd",
        "tts-1",
    ])))
    last_error = ""
    with httpx.Client(timeout=httpx.Timeout(connect=20.0, read=180.0, write=30.0, pool=20.0)) as client:
        for path in ("/v1/audio/speech", "/audio/speech"):
            for model in models:
                try:
                    response = client.post(
                        f"{base}{path}",
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json={
                            "model": model,
                            "voice": voice,
                            "input": text,
                            "response_format": "mp3",
                        },
                    )
                    if response.status_code >= 400:
                        last_error = f"{path} model={model} status={response.status_code}"
                        continue
                    if response.content:
                        log.info("PROPERTY_VIDEO_TTS_FALLBACK_OK provider=comet model=%s bytes=%s", model, len(response.content))
                        return bytes(response.content)
                except Exception as exc:
                    last_error = f"{path} model={model} error={type(exc).__name__}"
    log.warning("PROPERTY_VIDEO_TTS_FALLBACK_FAILED provider=comet error=%s", last_error)
    return None


async def create_narration_plan(
    analysis: list[dict], scenes, language: str, voice: str, *,
    user_id: int = 0, chat_id: int = 0,
    writer: Callable[..., Awaitable[str]] | None = None,
) -> dict:
    """Create one factual, word-bounded line for every montage slot."""
    language = "en" if str(language).lower() == "en" else "ru"
    voice = voice if voice in VOICE_MAP else "female"
    budgets = narration_word_budgets(scenes)
    facts = []
    for index, scene in enumerate(scenes):
        facts.append({
            "scene": index + 1,
            "seconds": float(scene.output_seconds),
            "max_words": budgets[index],
            "source": _analysis_item(analysis, scene.photo_index),
            "target": _analysis_item(analysis, scene.next_photo_index),
        })
    prompt = (
        "Write concise voice-over for a real-estate video. Return JSON only as "
        "{\"scenes\":[{\"scene\":1,\"text\":\"...\"}]}. "
        f"Write in {'English' if language == 'en' else 'Russian'}. "
        "Use only facts explicitly present below. Never invent privacy, room count, brands, equipment, "
        "amenities or a sea view. Use one natural sentence per scene, obey max_words, avoid repetition, "
        "sales hype and addresses. Synchronize each sentence with its scene.\nFACTS:\n" +
        json.dumps(facts, ensure_ascii=False)
    )
    if writer is None:
        writer = _property_json_request
    if callable(writer):
        try:
            if writer is _property_json_request:
                response = await writer(
                    prompt,
                    "You are a factual luxury real-estate voice-over editor. Output strict JSON only.",
                )
            else:
                response = await writer(
                    prompt, user_id=user_id or None, chat_id=chat_id or None,
                    extra_system="You are a factual luxury real-estate voice-over editor. Output strict JSON only.",
                )
            parsed = parse_narration_plan(response, scenes, language, voice)
            if parsed:
                return parsed
        except Exception:
            log.warning("PROPERTY_VIDEO_AUTO_NARRATION_FAILED", exc_info=True)
    return _fallback_narration(analysis, scenes, language, voice)


async def create_manual_narration_plan(
    text: str, scenes, language: str, voice: str, *,
    user_id: int = 0, chat_id: int = 0,
    writer: Callable[..., Awaitable[str]] | None = None,
) -> dict:
    """Rewrite a user's description into complete, timed scene lines."""
    source = " ".join(str(text or "").split())
    if not source:
        raise ValueError("Narration text is empty")
    language = "en" if str(language).lower() == "en" else "ru"
    voice = voice if voice in VOICE_MAP else "female"
    budgets = narration_word_budgets(scenes)
    slots = [
        {"scene": index + 1, "seconds": float(scene.output_seconds), "max_words": budget}
        for index, (scene, budget) in enumerate(zip(scenes, budgets))
    ]
    prompt = (
        "Rewrite the user's real-estate description as synchronized voice-over. "
        f"Return JSON only as {{\"scenes\":[{{\"scene\":1,\"text\":\"...\"}}]}} with exactly {len(scenes)} scenes. "
        f"Write in {'English' if language == 'en' else 'Russian'}. "
        "Use only claims from USER TEXT. Keep the property's location and strongest features when they fit. "
        "Preserve the final call to action in the final scene. Condense aggressively when needed. "
        "Every line must be a complete natural phrase, must fit max_words, and must never end mid-thought. "
        "Correct spelling and grammar without changing the meaning. Do not add facts.\n"
        f"SLOTS: {json.dumps(slots, ensure_ascii=False)}\nUSER TEXT: {source}"
    )
    if writer is None:
        writer = _property_json_request
    parsed = None
    try:
        if writer is _property_json_request:
            response = await writer(
                prompt,
                "You edit concise property-ad narration. Keep user claims, timing and final CTA. Output strict JSON only.",
            )
        else:
            response = await writer(
                prompt, user_id=user_id or None, chat_id=chat_id or None,
                extra_system="You edit concise property-ad narration. Output strict JSON only.",
            )
        parsed = parse_narration_plan(response, scenes, language, voice)
    except Exception:
        log.warning("PROPERTY_VIDEO_MANUAL_NARRATION_REWRITE_FAILED", exc_info=True)
    if not parsed:
        if len(source.split()) > sum(budgets):
            limit = sum(budgets)
            raise PropertyAudioError(
                f"Не удалось автоматически сократить текст до {limit} слов. "
                "Попробуйте ещё раз или отправьте более короткое описание."
                if language == "ru"
                else f"The script could not be shortened to {limit} words. Retry or send a shorter description."
            )
        parsed = manual_narration_plan(source, scenes, language, voice)
    source_words = len(source.split())
    script_words = len(str(parsed.get("full_text") or "").split())
    parsed["source_word_count"] = source_words
    parsed["script_word_count"] = script_words
    parsed["condensed"] = script_words < source_words
    if parsed["condensed"]:
        parsed["notice"] = (
            f"Текст сокращён с {source_words} до {script_words} слов, чтобы диктор успел за роликом."
            if language == "ru"
            else f"The script was shortened from {source_words} to {script_words} words to fit the video."
        )
    return parsed


def manual_narration_plan(text: str, scenes, language: str, voice: str) -> dict:
    """Distribute an edited script across scenes, preferring one line per scene."""
    cleaned = str(text or "").strip()
    lines = [line.strip(" -\t") for line in cleaned.splitlines() if line.strip(" -\t")]
    if len(lines) != len(scenes):
        lines = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
    if len(lines) != len(scenes):
        words = cleaned.split()
        lines = []
        cursor = 0
        budgets = narration_word_budgets(scenes)
        for index, budget in enumerate(budgets):
            remaining_scenes = len(budgets) - index
            remaining_words = len(words) - cursor
            take = max(1, min(budget, (remaining_words + remaining_scenes - 1) // remaining_scenes))
            lines.append(" ".join(words[cursor:cursor + take]))
            cursor += take
    value = parse_narration_plan({"scenes": [{"text": line} for line in lines]}, scenes, language, voice)
    if not value:
        raise ValueError("Narration must contain text for every scene")
    return value


def _probe_seconds(path: Path) -> float:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ], check=True, capture_output=True, text=True, timeout=30)
    return float(result.stdout.strip())


def _build_voice_timeline(segment_paths: list[Path], durations: list[float], output: Path) -> str:
    if len(segment_paths) != len(durations) or not segment_paths:
        raise PropertyAudioError("Narration segments do not match the scene plan")
    normalized = []
    output.parent.mkdir(parents=True, exist_ok=True)
    for index, (source, slot) in enumerate(zip(segment_paths, durations)):
        source_seconds = _probe_seconds(source)
        available = max(0.8, float(slot) - 0.55)
        tempo = max(0.85, source_seconds / available)
        if tempo > 1.25:
            raise PropertyAudioError(f"Narration for scene {index + 1} is too long")
        target = output.parent / f"voice_slot_{index:02d}.wav"
        subprocess.run([
            "ffmpeg", "-nostdin", "-y", "-i", str(source),
            "-af", (
                f"atempo={tempo:.8f},loudnorm=I=-16:TP=-1.5:LRA=7,"
                f"adelay=250,apad=whole_dur={float(slot):.3f},atrim=duration={float(slot):.3f}"
            ),
            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(target),
        ], check=True, capture_output=True, timeout=120)
        normalized.append(target)
    manifest = output.parent / "voice_concat.txt"
    manifest.write_text("".join(f"file '{path}'\n" for path in normalized), encoding="utf-8")
    subprocess.run([
        "ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(manifest),
        "-c:a", "pcm_s16le", str(output),
    ], check=True, capture_output=True, timeout=180)
    return str(output)


async def render_voice_track(
    plan: dict, scene_durations: list[float], output_dir: str, *,
    tts_renderer: Callable[[str, str], bytes | None] | None = None,
    on_request_start=None,
) -> str:
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    voice = VOICE_MAP.get(str(plan.get("voice") or "female"), "nova")
    if tts_renderer is None:
        import main as production_main
        renderer = production_main._tts_bytes_sync
        def default_renderer(text, selected):
            return renderer(text, "mp3", selected) or _comet_tts_bytes_sync(text, selected)
        tts_renderer = default_renderer
    paths = []
    for index, segment in enumerate(plan.get("segments") or []):
        path = folder / f"voice_source_{index:02d}.mp3"
        if path.is_file() and path.stat().st_size > 0:
            paths.append(path)
            continue
        if callable(on_request_start):
            on_request_start(index)
        data = await asyncio.to_thread(tts_renderer, str(segment.get("text") or ""), voice)
        if not data:
            raise PropertyAudioError(f"TTS did not return scene {index + 1}")
        path.write_bytes(bytes(data))
        paths.append(path)
    return await asyncio.to_thread(
        _build_voice_timeline, paths, [float(value) for value in scene_durations], folder / "voice_master.wav"
    )


def recover_voice_track(plan: dict, scene_durations: list[float], output_dir: str) -> str:
    """Rebuild a narration timeline only from already saved TTS responses."""
    folder = Path(output_dir)
    segments = list(plan.get("segments") or [])
    paths = [folder / f"voice_source_{index:02d}.mp3" for index in range(len(segments))]
    if len(paths) != len(scene_durations) or not paths or not all(path.is_file() and path.stat().st_size > 0 for path in paths):
        raise PropertyAudioError("saved narration segments are incomplete")
    return _build_voice_timeline(paths, [float(value) for value in scene_durations], folder / "voice_master.wav")


async def render_music_track(update, duration: int, output_dir: str, *, on_task_id=None) -> str:
    import main as production_main
    renderer = getattr(production_main, "_run_suno_music_result_bytes", None)
    if not callable(renderer):
        raise PropertyAudioError("Suno transport is unavailable")
    data = await renderer(update, LUXURY_LOUNGE_BRIEF, target_duration_s=int(duration), on_provider_state=(
        (lambda key, value: on_task_id(str(value)) if key == "suno_task_id" and callable(on_task_id) else None)
    ))
    if not data:
        raise PropertyAudioError("Suno did not return background music")
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "music_source.mp3"
    path.write_bytes(bytes(data))
    return str(path)


async def recover_music_track(task_id: str, output_dir: str) -> str:
    """Fetch an already submitted Suno task without creating another task."""
    task_id = str(task_id or "").strip()
    if not task_id or task_id.startswith("suno-submit:"):
        raise PropertyAudioError("saved Suno task id is unavailable")
    import httpx
    import main as production_main
    key = str(getattr(production_main, "SUNO_API_KEY", "") or "")
    base = str(getattr(production_main, "SUNO_BASE_URL", "") or "").rstrip("/")
    if not key or not base:
        raise PropertyAudioError("Suno recovery transport is unavailable")
    headers = {"Authorization": f"Bearer {key}", "Accept": "audio/mpeg,audio/*,application/json"}
    configured = str(getattr(production_main, "SUNO_STATUS_PATH", "/suno/fetch/{id}"))
    paths = [configured, "/suno/fetch/{id}", "/suno/v1/music/{id}", "/api/v1/task/{id}", "/v1/tasks/{id}"]

    def _audio_url(value) -> str | None:
        extract = getattr(production_main, "_extract_first_url")
        if isinstance(value, dict):
            for key_name in ("audio_url", "audioUrl", "stream_audio_url", "source_audio_url", "audio"):
                found = extract(value.get(key_name))
                if found:
                    return found
            for nested_value in value.values():
                if isinstance(nested_value, (dict, list, tuple)):
                    found = _audio_url(nested_value)
                    if found:
                        return found
        elif isinstance(value, (list, tuple)):
            for nested_value in value:
                found = _audio_url(nested_value)
                if found:
                    return found
        return None

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        for template in dict.fromkeys(paths):
            try:
                response = await client.get(f"{base}{template}".format(id=task_id), headers=headers)
                if response.status_code >= 400:
                    continue
                payload = response.json() or {}
                nested = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else {}
                status = str(
                    payload.get("status") or payload.get("state") or payload.get("task_status")
                    or nested.get("status") or ""
                ).lower()
                if status in {"failed", "fail", "error", "canceled", "cancelled", "rejected"}:
                    raise PropertyAudioError("submitted Suno task failed")
                if status and status not in {"completed", "succeeded", "success", "finished", "done", "ready"}:
                    continue
                url = _audio_url(payload)
                if not url:
                    continue
                download = getattr(production_main, "_download_binary_from_url")
                data = await download(client, url, accept="audio/mpeg,audio/*,*/*;q=0.8", timeout_s=300.0)
                if data:
                    folder = Path(output_dir)
                    folder.mkdir(parents=True, exist_ok=True)
                    path = folder / "music_source.mp3"
                    candidate = folder / "music_source.recovering"
                    candidate.write_bytes(bytes(data))
                    probe = subprocess.run([
                        "ffprobe", "-v", "error", "-select_streams", "a:0",
                        "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(candidate),
                    ], capture_output=True, text=True, timeout=30)
                    if probe.returncode != 0 or "audio" not in probe.stdout.splitlines():
                        candidate.unlink(missing_ok=True)
                        continue
                    candidate.replace(path)
                    return str(path)
            except Exception:
                continue
    raise PropertyAudioError("submitted Suno track is not ready")


def mix_property_audio(
    video_path: str, output_path: str, duration: int, *,
    music_path: str = "", voice_path: str = "",
) -> str:
    """Mux scene-aware narration and ducked lounge music into a final MP4."""
    source = Path(video_path).resolve(strict=True)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    seconds = float(duration)
    if not music_path and not voice_path:
        temporary = target.with_name(target.stem + ".noaudio.tmp.mp4") if source == target.resolve() else target
        subprocess.run([
            "ffmpeg", "-nostdin", "-y", "-i", str(source), "-map", "0:v:0", "-c:v", "copy",
            "-an", "-movflags", "+faststart", str(temporary),
        ], check=True, capture_output=True, timeout=int(os.getenv("PROPERTY_VIDEO_FFMPEG_TIMEOUT_S", "600")))
        if temporary != target:
            temporary.replace(target)
        return str(target)

    command = ["ffmpeg", "-nostdin", "-y", "-i", str(source)]
    if music_path:
        command.extend(["-stream_loop", "-1", "-i", str(Path(music_path).resolve(strict=True))])
    if voice_path:
        command.extend(["-i", str(Path(voice_path).resolve(strict=True))])
    fade_out = max(0.0, seconds - 1.0)
    if music_path and voice_path:
        filters = (
            f"[1:a]atrim=duration={seconds:.3f},afade=t=in:st=0:d=0.4,"
            f"afade=t=out:st={fade_out:.3f}:d=1,loudnorm=I=-24:TP=-2:LRA=9[m];"
            f"[2:a]atrim=duration={seconds:.3f},apad=whole_dur={seconds:.3f},"
            "loudnorm=I=-16:TP=-1.5:LRA=7,asplit=2[vside][v];"
            "[m][vside]sidechaincompress=threshold=0.025:ratio=8:attack=20:release=500[ducked];"
            f"[ducked][v]amix=inputs=2:duration=longest:normalize=0,atrim=duration={seconds:.3f}[a]"
        )
    elif music_path:
        filters = (
            f"[1:a]atrim=duration={seconds:.3f},afade=t=in:st=0:d=0.4,"
            f"afade=t=out:st={fade_out:.3f}:d=1,loudnorm=I=-22:TP=-2:LRA=9[a]"
        )
    else:
        filters = (
            f"[1:a]atrim=duration={seconds:.3f},apad=whole_dur={seconds:.3f},"
            f"loudnorm=I=-16:TP=-1.5:LRA=7,atrim=duration={seconds:.3f}[a]"
        )
    command.extend([
        "-filter_complex", filters, "-map", "0:v:0", "-map", "[a]", "-t", f"{seconds:.3f}",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(target),
    ])
    subprocess.run(command, check=True, capture_output=True, timeout=int(os.getenv("PROPERTY_VIDEO_FFMPEG_TIMEOUT_S", "600")))
    return str(target)
