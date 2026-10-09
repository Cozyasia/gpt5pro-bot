"""Immutable production contract for multi-scene AI music videos."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any, Iterable


ALLOWED_ASPECTS = frozenset({"9:16", "16:9", "1:1", "4:5", "3:4", "4:3"})


def _clean_text(value: Any, field: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        raise ValueError(f"scene {field} is required")
    return text


def _state_items(value: Any) -> tuple[str, ...]:
    if isinstance(value, dict):
        raw: Iterable[Any] = (f"{key}={value[key]}" for key in sorted(value))
    elif isinstance(value, (list, tuple)):
        raw = value
    else:
        raise ValueError("scene world_state must be a list or object")
    items = tuple(re.sub(r"\s+", " ", str(item or "")).strip() for item in raw)
    if not items or any(not item for item in items):
        raise ValueError("scene world_state must not be empty")
    return items


def _text_items(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("completed_actions must be a list")
    return tuple(text for item in value if (text := re.sub(r"\s+", " ", str(item or "")).strip()))


@dataclass(frozen=True, slots=True)
class SceneContract:
    index: int
    start_s: float
    end_s: float
    action: str
    start_state: str
    end_state: str
    world_state: tuple[str, ...]
    completed_actions: tuple[str, ...]
    future_count: int
    lip_sync_start_s: float | None = None
    lip_sync_end_s: float | None = None

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    @property
    def has_lip_sync(self) -> bool:
        return self.lip_sync_start_s is not None and self.lip_sync_end_s is not None


@dataclass(frozen=True, slots=True)
class ScenePlan:
    duration_s: int
    aspect: str
    vocal_start_s: float | None
    scenes: tuple[SceneContract, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _number(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc


def scene_plan_from_dict(
    payload: dict[str, Any],
    *,
    expected_duration_s: int,
    expected_aspect: str,
    require_lip_sync: bool = False,
) -> ScenePlan:
    """Validate untrusted compiler JSON and return a frozen production plan."""
    if not isinstance(payload, dict):
        raise ValueError("ScenePlan payload must be an object")
    duration_s = int(_number(payload.get("duration_s"), "duration_s"))
    if duration_s != int(expected_duration_s):
        raise ValueError(f"ScenePlan duration {duration_s} does not match approved duration {expected_duration_s}")
    aspect = str(payload.get("aspect") or "").strip()
    if aspect not in ALLOWED_ASPECTS or aspect != expected_aspect:
        raise ValueError(f"ScenePlan aspect {aspect!r} does not match approved aspect {expected_aspect!r}")
    vocal_raw = payload.get("vocal_start_s")
    vocal_start_s = None if vocal_raw is None else _number(vocal_raw, "vocal_start_s")
    if vocal_start_s is not None and not (0 <= vocal_start_s < duration_s):
        raise ValueError("vocal_start_s must fall inside the clip")

    raw_scenes = payload.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("ScenePlan scenes must be a non-empty list")
    scenes: list[SceneContract] = []
    cursor = 0.0
    for position, raw in enumerate(raw_scenes, start=1):
        if not isinstance(raw, dict):
            raise ValueError("each scene must be an object")
        index = int(_number(raw.get("index"), "scene index"))
        start_s = _number(raw.get("start_s"), "scene start_s")
        end_s = _number(raw.get("end_s"), "scene end_s")
        if index != position:
            raise ValueError("scene indexes must be sequential and one-based")
        if abs(start_s - cursor) > 1e-6:
            raise ValueError("scene ranges must be contiguous without gaps or overlaps")
        if end_s <= start_s or end_s - start_s > 10.000001:
            raise ValueError("each scene must last more than 0 and at most 10 seconds")

        lip_start_raw = raw.get("lip_sync_start_s")
        lip_end_raw = raw.get("lip_sync_end_s")
        if (lip_start_raw is None) != (lip_end_raw is None):
            raise ValueError("lip-sync start and end must be provided together")
        lip_start = None if lip_start_raw is None else _number(lip_start_raw, "lip_sync_start_s")
        lip_end = None if lip_end_raw is None else _number(lip_end_raw, "lip_sync_end_s")
        if lip_start is not None and lip_end is not None:
            if lip_start < start_s or lip_end > end_s or lip_end <= lip_start:
                raise ValueError("lip-sync interval must stay inside its scene")
            if not 2.0 <= lip_end - lip_start <= 10.0:
                raise ValueError("lip-sync interval must be 2 to 10 seconds")

        scenes.append(SceneContract(
            index=index,
            start_s=start_s,
            end_s=end_s,
            action=_clean_text(raw.get("action"), "action"),
            start_state=_clean_text(raw.get("start_state"), "start_state"),
            end_state=_clean_text(raw.get("end_state"), "end_state"),
            world_state=_state_items(raw.get("world_state")),
            completed_actions=_text_items(raw.get("completed_actions")),
            future_count=max(0, int(_number(raw.get("future_count", 0), "future_count"))),
            lip_sync_start_s=lip_start,
            lip_sync_end_s=lip_end,
        ))
        cursor = end_s
    if abs(cursor - duration_s) > 1e-6:
        raise ValueError("scene ranges must cover the full approved duration")
    if require_lip_sync and not any(scene.has_lip_sync for scene in scenes):
        raise ValueError("vocal ScenePlan requires at least one lip-sync interval")
    for scene in scenes:
        expected_future = len(scenes) - scene.index
        if scene.future_count != expected_future:
            raise ValueError("scene future_count does not match the ordered plan")
    return ScenePlan(duration_s, aspect, vocal_start_s, tuple(scenes))


_TIMELINE_RE = re.compile(
    r"(?im)^[ \t]*(\d{1,3})\s*[-–—]\s*(\d{1,3})\s*"
    r"(?:сек(?:унд\w*)?|s(?:ec(?:ond)?s?)?)?\s*[:：]\s*"
)


def scene_plan_from_explicit_timeline(
    video_brief: str,
    *,
    duration_s: int,
    aspect: str,
    wants_vocals: bool,
    vocal_start_s: float | None,
) -> ScenePlan:
    """Compile already timestamped user direction without an LLM rewrite."""
    source = (video_brief or "").replace("\r\n", "\n").strip()
    markers = list(_TIMELINE_RE.finditer(source))
    if not markers:
        raise ValueError("explicit scene timeline is missing")
    raw_scenes: list[dict[str, Any]] = []
    completed: list[str] = []
    for offset, marker in enumerate(markers):
        end = markers[offset + 1].start() if offset + 1 < len(markers) else len(source)
        action = source[marker.end():end]
        action = re.split(
            r"(?im)\n\s*(?:обязательные\s+условия|global\s+constraints|continuity\s+rules)\s*:",
            action,
            maxsplit=1,
        )[0]
        action = re.sub(r"\s+", " ", action).strip(" ;\n\t")
        start_s, end_s = float(marker.group(1)), float(marker.group(2))
        start_state = "Supplied starting keyframe." if offset == 0 else raw_scenes[-1]["end_state"]
        end_state = f"Physical end state after: {action}"
        face_visible = bool(re.search(r"(лиц|профил|3/4|фронтал|face|profile|close[- ]?up)", action, re.I))
        lip_start = max(start_s, float(vocal_start_s or 0.0)) if wants_vocals and face_visible else None
        lip_end = end_s if lip_start is not None and end_s - lip_start >= 2 else None
        if lip_end is None:
            lip_start = None
        raw_scenes.append({
            "index": offset + 1,
            "start_s": start_s,
            "end_s": end_s,
            "action": action,
            "start_state": start_state,
            "end_state": end_state,
            "world_state": [f"scene={offset + 1}", f"current_action={action}"],
            "completed_actions": tuple(completed),
            "future_count": len(markers) - offset - 1,
            "lip_sync_start_s": lip_start,
            "lip_sync_end_s": lip_end,
        })
        completed.append(action)
    return scene_plan_from_dict(
        {"duration_s": duration_s, "aspect": aspect, "vocal_start_s": vocal_start_s, "scenes": raw_scenes},
        expected_duration_s=duration_s,
        expected_aspect=aspect,
        require_lip_sync=False,
    )


def _clock(seconds: float) -> str:
    whole = int(round(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def render_scene_plan_review(plan: ScenePlan, music_brief: str, video_brief: str) -> str:
    """Render all source text and the exact production scene contracts."""
    sections = [
        "🎬 Сценарий AI-видеоклипа на утверждение",
        f"🎵 ПЕСНЯ\n{(music_brief or '').strip()}",
        f"🎥 КЛИП\n{(video_brief or '').strip()}",
        f"Параметры: {plan.duration_s} секунд · {len(plan.scenes)} сцен · формат {plan.aspect}.",
        "🎞 РЕЖИССЁРСКАЯ РАЗБИВКА — это точный план, который получит генератор",
    ]
    for scene in plan.scenes:
        lip = "не применяется"
        if scene.has_lip_sync:
            lip = f"{_clock(scene.lip_sync_start_s or 0)}–{_clock(scene.lip_sync_end_s or 0)}"
        completed = "; ".join(scene.completed_actions) or "нет"
        world = "; ".join(scene.world_state)
        sections.append(
            f"СЦЕНА {scene.index} · {_clock(scene.start_s)}–{_clock(scene.end_s)}\n"
            f"Действие: {scene.action}\n"
            f"START: {scene.start_state}\n"
            f"END: {scene.end_state}\n"
            f"Состояние мира: {world}\n"
            f"Завершённые действия: {completed}\n"
            f"Будущих закрытых блоков: {scene.future_count}\n"
            f"Lip-sync: {lip}"
        )
    return "\n\n".join(sections)


def chunk_review_messages(text: str, *, limit: int = 3900) -> list[str]:
    """Split Telegram text losslessly, preferring paragraph boundaries."""
    if limit < 100:
        raise ValueError("review chunk limit is too small")
    remaining = str(text or "")
    chunks: list[str] = []
    while len(remaining) > limit:
        split_at = remaining.rfind("\n\n", 0, limit + 1)
        if split_at < max(1, limit // 3):
            split_at = limit
        else:
            split_at += 2
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining or not chunks:
        chunks.append(remaining)
    return chunks

