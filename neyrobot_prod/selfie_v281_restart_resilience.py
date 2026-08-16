# -*- coding: utf-8 -*-
"""AI Selfie restart resilience for Render rolling deploys/restarts.

V281 keeps the 3-photo upload session on the persistent Render disk so a process
restart does not drop the user into the generic photo handler midway through the
AI Selfie flow. It intentionally does not persist provider secrets or arbitrary
Telegram context data.
"""
from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any

VERSION = "v281-selfie-restart-resilience-2026-08-16"
_INSTALLED = False
_ORIGINAL_PHOTO_CALLBACK: Any | None = None
_ORIGINAL_PHOTO_MEDIA: Any | None = None


def _root() -> Path:
    configured = str(os.getenv("AI_SELFIE_SESSION_DIR") or "").strip()
    if configured:
        root = Path(configured)
    else:
        db_path = Path(str(os.getenv("DB_PATH") or "/data/subs.db"))
        root = db_path.parent / "ai_selfie_sessions"
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return root
    except Exception:
        fallback = Path("/tmp/ai_selfie_sessions")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _user_id(update: Any) -> int | None:
    user = getattr(update, "effective_user", None)
    if user is None:
        query = getattr(update, "callback_query", None)
        user = getattr(query, "from_user", None) if query is not None else None
    try:
        return int(user.id) if user is not None else None
    except Exception:
        return None


def _dir(user_id: int) -> Path:
    path = _root() / str(int(user_id))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def _clear(user_id: int) -> None:
    path = _root() / str(int(user_id))
    if not path.exists():
        return
    for item in path.iterdir():
        with contextlib.suppress(Exception):
            item.unlink()
    with contextlib.suppress(Exception):
        path.rmdir()


def _persist(context: Any, user_id: int) -> None:
    """Persist only the compact AI Selfie session contract."""
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219

    photos = list(v219._photos(context))
    data = getattr(context, "user_data", {}) or {}
    active = bool(data.get("awaiting_ai_selfie_photo")) or bool(photos) or bool(data.get("cs201_character"))
    if not active:
        return

    path = _dir(user_id)
    for idx, raw in enumerate(photos[:3], 1):
        target = path / f"photo{idx}.bin"
        tmp = path / f"photo{idx}.tmp"
        tmp.write_bytes(bytes(raw))
        os.replace(tmp, target)
    for idx in range(len(photos) + 1, 4):
        with contextlib.suppress(Exception):
            (path / f"photo{idx}.bin").unlink()

    scene_image = data.get("cs215_scene_image")
    if isinstance(scene_image, (bytes, bytearray)) and len(scene_image) > 0:
        tmp = path / "scene.tmp"
        tmp.write_bytes(bytes(scene_image))
        os.replace(tmp, path / "scene.bin")

    allowed = (
        "awaiting_ai_selfie_photo",
        "cs201_character",
        "cs215_shot_mode",
        "cs215_scene_mode",
        "cs215_scene_text",
        "cs215_scene_label",
        "cs215_await_scene_image",
    )
    state: dict[str, Any] = {"version": VERSION, "updated_at": time.time(), "photo_count": len(photos[:3])}
    for key in allowed:
        value = data.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            if value not in (None, "", False):
                state[key] = value
    _atomic_json(path / "manifest.json", state)
    print(f"[neyrobot-prod] AI_SELFIE_V281_STATE stage=saved user_id={user_id} photos={len(photos[:3])}", flush=True)


def _restore(update: Any, context: Any, user_id: int) -> bool:
    """Restore the upload/navigation session after a process restart."""
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_v219_triref_scene_owner as v219
    from neyrobot_prod import selfie_v218_runtime_owner as owner

    manifest = _root() / str(int(user_id)) / "manifest.json"
    if not manifest.exists():
        return False
    try:
        state = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return False
    max_age = max(900.0, float(os.getenv("AI_SELFIE_SESSION_TTL_S") or "43200"))
    if time.time() - float(state.get("updated_at") or 0.0) > max_age:
        _clear(user_id)
        return False

    current = list(v219._photos(context))
    if not current:
        restored: list[bytes] = []
        path = manifest.parent
        for idx in range(1, 4):
            file = path / f"photo{idx}.bin"
            if file.exists():
                raw = file.read_bytes()
                if len(raw) > 1024:
                    restored.append(raw)
        if restored:
            v219._reset_photos(context)
            for raw in restored:
                v219._append_photo(context, raw)

    data = context.user_data
    for key in (
        "awaiting_ai_selfie_photo",
        "cs201_character",
        "cs215_shot_mode",
        "cs215_scene_mode",
        "cs215_scene_text",
        "cs215_scene_label",
        "cs215_await_scene_image",
    ):
        if key not in data and key in state:
            data[key] = state[key]
    scene = manifest.parent / "scene.bin"
    if "cs215_scene_image" not in data and scene.exists():
        raw = scene.read_bytes()
        if len(raw) > 1024:
            data["cs215_scene_image"] = raw

    # If fewer than 3 refs were saved, force the high-priority selfie media owner
    # to continue receiving photos instead of letting the generic photo handler win.
    refs = list(v219._photos(context))
    if 0 < len(refs) < 3:
        data["awaiting_ai_selfie_photo"] = True

    runtime = owner._runtime()
    if runtime is not None:
        with contextlib.suppress(Exception):
            base._activate(runtime, context, int(user_id))
    print(f"[neyrobot-prod] AI_SELFIE_V281_STATE stage=restored user_id={user_id} photos={len(refs)}", flush=True)
    return True


async def _photo_callback(update: Any, context: Any) -> None:
    global _ORIGINAL_PHOTO_CALLBACK
    uid = _user_id(update)
    query = getattr(update, "callback_query", None)
    data = str(getattr(query, "data", "") or "")
    if uid is not None and data in {"cs201:photo", "act:fun:aiselfie_upload", "cs201:reuse:photos"}:
        _clear(uid)
    elif uid is not None:
        _restore(update, context, uid)
    try:
        if callable(_ORIGINAL_PHOTO_CALLBACK):
            await _ORIGINAL_PHOTO_CALLBACK(update, context)
    finally:
        if uid is not None:
            with contextlib.suppress(Exception):
                _persist(context, uid)


async def _photo_media(update: Any, context: Any) -> None:
    global _ORIGINAL_PHOTO_MEDIA
    uid = _user_id(update)
    if uid is not None:
        with contextlib.suppress(Exception):
            _restore(update, context, uid)
    try:
        if callable(_ORIGINAL_PHOTO_MEDIA):
            await _ORIGINAL_PHOTO_MEDIA(update, context)
    finally:
        if uid is not None:
            with contextlib.suppress(Exception):
                _persist(context, uid)


def install() -> bool:
    global _INSTALLED, _ORIGINAL_PHOTO_CALLBACK, _ORIGINAL_PHOTO_MEDIA
    if _INSTALLED:
        return True
    from neyrobot_prod import selfie_v218_runtime_owner as owner

    if getattr(owner, "_v281_restart_resilience", False):
        _INSTALLED = True
        return True
    _ORIGINAL_PHOTO_CALLBACK = owner._photo_callback
    _ORIGINAL_PHOTO_MEDIA = owner._photo_media
    owner._photo_callback = _photo_callback
    owner._photo_media = _photo_media
    setattr(owner, "_v281_restart_resilience", True)
    _INSTALLED = True
    print(f"[neyrobot-prod] V281 AI Selfie restart resilience installed version={VERSION} dir={_root()}", flush=True)
    return True


__all__ = ["VERSION", "install"]
