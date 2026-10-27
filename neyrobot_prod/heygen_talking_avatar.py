# -*- coding: utf-8 -*-
"""Telegram flow for HeyGen talking-avatar videos.

The module is installed before main.py builds the Telegram application. It owns
the HeyGen command and the existing fun:avatar menu button, leaving the Veo
and legacy avatar paths untouched.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any

BASE_URL = "https://api.heygen.com"
FLOW_KEY = "_heygen_talking_avatar_v1"
CATALOG_TTL_SECONDS = 15 * 60
_CATALOG: tuple[float, list["Avatar"], list["Voice"]] | None = None


@dataclass(frozen=True)
class Avatar:
    avatar_id: str
    name: str
    gender: str = ""
    preview_image_url: str = ""
    group_id: str = ""


@dataclass(frozen=True)
class Voice:
    voice_id: str
    name: str
    language: str = ""
    gender: str = ""
    preview_audio_url: str = ""


def _str(value: Any) -> str:
    return str(value or "").strip()


def avatar_from_api(raw: dict[str, Any]) -> Avatar:
    return Avatar(
        avatar_id=_str(raw.get("avatar_id") or raw.get("id")),
        name=_str(raw.get("name") or raw.get("avatar_name")) or "Без имени",
        gender=_str(raw.get("gender")),
        preview_image_url=_str(raw.get("preview_image_url") or raw.get("preview_url") or raw.get("image_url")),
        group_id=_str(raw.get("group_id")),
    )


def voice_from_api(raw: dict[str, Any]) -> Voice:
    return Voice(
        voice_id=_str(raw.get("voice_id") or raw.get("id")),
        name=_str(raw.get("name") or raw.get("voice_name")) or "Без имени",
        language=_str(raw.get("language")),
        gender=_str(raw.get("gender")),
        preview_audio_url=_str(raw.get("preview_audio_url") or raw.get("preview_url") or raw.get("audio_url")),
    )


def build_talking_avatar_payload(*, avatar_id: str, voice_id: str, script: str, title: str) -> dict[str, Any]:
    avatar_id, voice_id, script = _str(avatar_id), _str(voice_id), _str(script)
    if not all((avatar_id, voice_id, script)):
        raise ValueError("avatar_id, voice_id and script are required")
    return {
        "type": "avatar",
        "avatar_id": avatar_id,
        "voice_id": voice_id,
        "script": script,
        "title": _str(title) or "Neyro-Bot Studio",
        "resolution": "1080p",
        "aspect_ratio": "9:16",
        "voice_settings": {"locale": "ru-RU"},
    }


def selection_key(user_id: int) -> str:
    return f"heygen-selection:{int(user_id)}"


def is_talking_avatar_entry_callback(data: str) -> bool:
    """Recognize both current and pre-v265 Telegram menu callback routes."""
    return _str(data) in {"act:fun:avatar", "fun:avatar"}


def video_engine_options(*, runway_enabled: bool) -> list[tuple[str, str]]:
    """Stable engine catalog for the text-video chooser.

    HeyGen is intentionally described as a presenter engine: its v3 Videos
    endpoint creates a talking avatar, not a general cinematic text-to-video
    scene.  The other engines retain their existing production handlers.
    """
    options = [
        ("heygen", "HeyGen · говорящий аватар"),
        ("sora", "Sora 2 · без людей"),
        ("kling", "Kling"),
        ("veo", "Google Veo 3.1 Fast"),
        ("seedance", "✨ Seedance 2.5 · 4–30 сек"),
    ]
    if runway_enabled:
        options.append(("runway", "Runway"))
    return options


def _runtime() -> Any | None:
    import sys
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _db_path() -> str:
    runtime = _runtime()
    return _str(getattr(runtime, "DB_PATH", "")) or _str(os.getenv("HEYGEN_PREFERENCES_DB_PATH")) or "/data/subs.db"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.execute("PRAGMA busy_timeout=15000")
    return con


def _ensure_storage() -> None:
    with _connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS heygen_avatar_preferences (
                user_id INTEGER PRIMARY KEY,
                avatar_id TEXT NOT NULL,
                avatar_name TEXT NOT NULL DEFAULT '',
                voice_id TEXT NOT NULL,
                voice_name TEXT NOT NULL DEFAULT '',
                updated_ts INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS heygen_avatar_jobs (
                job_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                avatar_id TEXT NOT NULL,
                voice_id TEXT NOT NULL,
                script_sha256 TEXT NOT NULL,
                provider_video_id TEXT,
                state TEXT NOT NULL,
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL,
                result_url TEXT,
                error_text TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_heygen_avatar_jobs_state
                ON heygen_avatar_jobs(state, updated_ts);
            """
        )


def _save_preference(user_id: int, avatar: Avatar, voice: Voice) -> None:
    _ensure_storage()
    now = int(time.time())
    with _connect() as con:
        con.execute(
            """
            INSERT INTO heygen_avatar_preferences
              (user_id, avatar_id, avatar_name, voice_id, voice_name, updated_ts)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              avatar_id=excluded.avatar_id, avatar_name=excluded.avatar_name,
              voice_id=excluded.voice_id, voice_name=excluded.voice_name,
              updated_ts=excluded.updated_ts
            """,
            (int(user_id), avatar.avatar_id, avatar.name, voice.voice_id, voice.name, now),
        )



def select_vertical_look(base: Avatar, looks_payload: Any) -> Avatar:
    """Return the usable portrait look from an avatar group when HeyGen supplies one."""
    rows = _rows(looks_payload, ("looks", "avatars", "avatar_list"))
    choices = [avatar_from_api(row) for row in rows]
    choices = [choice for choice in choices if choice.avatar_id]
    if not choices:
        return base

    def score(raw: dict[str, Any]) -> tuple[int, int]:
        aspect = _str(raw.get("aspect_ratio") or raw.get("aspectRatio") or raw.get("orientation")).lower()
        is_vertical = int(aspect in {"9:16", "vertical", "portrait"})
        is_default = int(bool(raw.get("is_default") or raw.get("default")))
        return is_vertical, is_default

    ranked = sorted(
        ((score(raw), avatar_from_api(raw)) for raw in rows if _str(raw.get("avatar_id") or raw.get("id"))),
        key=lambda item: item[0],
        reverse=True,
    )
    chosen = ranked[0][1] if ranked else choices[0]
    return Avatar(
        avatar_id=chosen.avatar_id,
        name=chosen.name if chosen.name != "Без имени" else base.name,
        gender=chosen.gender or base.gender,
        preview_image_url=chosen.preview_image_url or base.preview_image_url,
        group_id=base.group_id,
    )


def _rows(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    for key in ("data", "result"):
        nested = payload.get(key)
        if isinstance(nested, (dict, list)):
            found = _rows(nested, keys)
            if found:
                return found
    return []


def video_ready_avatars_from_looks(looks_payload: Any) -> list[Avatar]:
    """Extract completed *look* IDs, which are the IDs accepted by POST /v3/videos.

    /v3/avatars lists avatar groups (``ag_...``), while the video endpoint
    requires the selected look (``lk_...``).  Showing group IDs in the picker
    creates a deterministic 404 ``avatar_not_found`` at submission time.
    """
    rows = _rows(looks_payload, ("looks", "avatars", "avatar_list"))
    ready = [
        avatar_from_api(raw)
        for raw in rows
        if _str(raw.get("id") or raw.get("avatar_id"))
        and _str(raw.get("status")).lower() not in {"processing", "pending", "failed", "error"}
    ]
    return sorted(
        ready,
        key=lambda avatar: (
            0 if _str(next((raw.get("preferred_orientation") for raw in rows if _str(raw.get("id") or raw.get("avatar_id")) == avatar.avatar_id), "")).lower() in {"portrait", "vertical", "9:16"} else 1,
            avatar.name.lower(),
        ),
    )


async def _fetch_json(path: str, *, params: dict[str, str] | None = None) -> Any:
    import httpx
    key = _str(os.getenv("HEYGEN_API_KEY"))
    if not key:
        raise RuntimeError("HEYGEN_API_KEY не задан")
    async with httpx.AsyncClient(timeout=35, follow_redirects=True) as client:
        response = await client.get(
            BASE_URL + path,
            headers={"X-Api-Key": key, "Accept": "application/json"},
            params=params,
        )
    response.raise_for_status()
    return response.json()


async def load_catalog() -> tuple[list[Avatar], list[Voice]]:
    global _CATALOG
    if _CATALOG and time.monotonic() - _CATALOG[0] < CATALOG_TTL_SECONDS:
        return _CATALOG[1], _CATALOG[2]
    looks_payload, voice_payload = await asyncio.gather(
        _fetch_json("/v3/avatars/looks", params={"ownership": "public", "limit": "50"}),
        _fetch_json("/v3/voices", params={"type": "public", "language": "ru", "limit": "50"}),
    )
    avatars = video_ready_avatars_from_looks(looks_payload)
    voices = [voice_from_api(row) for row in _rows(voice_payload, ("voices", "voice_list"))]
    voices = [x for x in voices if x.voice_id]
    if not avatars or not voices:
        raise RuntimeError("HeyGen не вернул доступные аватары или голоса")
    _CATALOG = (time.monotonic(), avatars, voices)
    return avatars, voices


def _flow(context: Any) -> dict[str, Any]:
    return context.user_data.setdefault(FLOW_KEY, {})


def _clear_flow(context: Any) -> None:
    context.user_data.pop(FLOW_KEY, None)


def _avatar_at(state: dict[str, Any]) -> Avatar:
    return state["avatars"][int(state.get("avatar_index", 0))]


def _voice_at(state: dict[str, Any]) -> Voice:
    return state["voices"][int(state.get("voice_index", 0))]


def _button(text: str, callback_data: str) -> Any:
    from telegram import InlineKeyboardButton
    return InlineKeyboardButton(text, callback_data=callback_data)


def _markup(rows: list[list[Any]]) -> Any:
    from telegram import InlineKeyboardMarkup
    return InlineKeyboardMarkup(rows)


def _avatar_markup(state: dict[str, Any]) -> Any:
    index, total = int(state.get("avatar_index", 0)), len(state["avatars"])
    nav: list[Any] = []
    if index:
        nav.append(_button("◀", "hg:ap"))
    nav.append(_button(f"{index + 1}/{total}", "hg:noop"))
    if index + 1 < total:
        nav.append(_button("▶", "hg:an"))
    return _markup([
        [_button("Выбрать этот образ", "hg:as")],
        nav,
        [_button("Отмена", "hg:cancel")],
    ])


def _voice_markup(state: dict[str, Any]) -> Any:
    index, total = int(state.get("voice_index", 0)), len(state["voices"])
    nav: list[Any] = []
    if index:
        nav.append(_button("◀", "hg:vp"))
    nav.append(_button(f"{index + 1}/{total}", "hg:noop"))
    if index + 1 < total:
        nav.append(_button("▶", "hg:vn"))
    return _markup([
        [_button("Выбрать этот голос", "hg:vs")],
        nav,
        [_button("← К аватарам", "hg:avatars"), _button("Отмена", "hg:cancel")],
    ])


def _confirm_markup() -> Any:
    return _markup([
        [_button("🎬 Создать ролик", "hg:confirm")],
        [_button("Сменить голос", "hg:voices"), _button("Сменить образ", "hg:avatars")],
        [_button("Отмена", "hg:cancel")],
    ])


def _entry_markup() -> Any:
    return _markup([
        [_button("🎭 HeyGen · выбрать образ и голос", "hg:entry:heygen")],
        [_button("📸 Kling Avatar · свой портрет", "hg:entry:kling")],
        [_button("⬅️ Назад в Развлечения", "hg:back:fun")],
    ])


def _video_engine_markup() -> Any:
    runtime = _runtime()
    runway_enabled = bool(getattr(runtime, "TEXT_VIDEO_ALLOW_RUNWAY", False))
    rows: list[list[Any]] = []
    for engine, label in video_engine_options(runway_enabled=runway_enabled):
        callback = "hg:tv:heygen" if engine == "heygen" else f"hg:tv:legacy:{engine}"
        rows.append([_button(label, callback)])
    rows.append([_button("⬅️ Назад в Развлечения", "hg:back:fun")])
    return _markup(rows)


async def _show_entry_menu(message: Any) -> None:
    await message.reply_text(
        "🗣 <b>Говорящий аватар</b>\n\n"
        "<b>HeyGen</b> — готовый профессиональный образ, выбор русского голоса и текст.\n"
        "<b>Kling Avatar</b> — ваш портрет + текст или записанный voice/audio.",
        parse_mode="HTML",
        reply_markup=_entry_markup(),
    )


async def _show_video_engine_menu(message: Any) -> None:
    await message.reply_text(
        "🎬 <b>Видео по тексту / голосу</b>\n\n"
        "Выберите движок. <b>Veo</b> создаёт видеоряд и нативный звук сам. "
        "<b>HeyGen</b> создаёт видео с говорящим аватаром: далее выберите образ и русский голос.",
        parse_mode="HTML",
        reply_markup=_video_engine_markup(),
    )


async def _delegate_to_legacy_avatar(update: Any, context: Any) -> None:
    handler = getattr(_runtime(), "on_mode_cb", None)
    if not callable(handler):
        raise RuntimeError("Старый режим Kling Avatar недоступен: обработчик не найден")
    await handler(update, context)


async def _delegate_to_legacy_text_engine(update: Any, context: Any, engine: str) -> None:
    handler = getattr(_runtime(), "_handle_textvideo_engine_choice", None)
    if not callable(handler):
        raise RuntimeError("Выбранный видеодвижок временно недоступен")
    await handler(update, context, update.callback_query, engine, prefix="act")


async def _back_to_fun_menu(update: Any, context: Any) -> None:
    handler = getattr(_runtime(), "_send_mode_menu", None)
    if callable(handler):
        await handler(update, context, "fun")
    else:
        await update.callback_query.message.reply_text("Откройте «Развлечения» и выберите нужный режим.")


async def _show_avatar(message: Any, state: dict[str, Any]) -> None:
    avatar = _avatar_at(state)
    text = (
        f"🧑‍🎤 <b>Выберите образ</b>\n\n"
        f"<b>{avatar.name}</b>\n"
        f"Пол: {avatar.gender or 'не указан'}\n"
        f"Образ {int(state.get('avatar_index', 0)) + 1} из {len(state['avatars'])}"
    )
    if avatar.preview_image_url:
        with contextlib.suppress(Exception):
            await message.reply_photo(
                photo=avatar.preview_image_url,
                caption=text,
                parse_mode="HTML",
                reply_markup=_avatar_markup(state),
            )
            return
    await message.reply_text(text, parse_mode="HTML", reply_markup=_avatar_markup(state))


async def _show_voice(message: Any, state: dict[str, Any]) -> None:
    voice = _voice_at(state)
    text = (
        f"🎙 <b>Выберите голос</b>\n\n"
        f"<b>{voice.name}</b>\n"
        f"Язык: {voice.language or 'не указан'}\n"
        f"Голос {int(state.get('voice_index', 0)) + 1} из {len(state['voices'])}"
    )
    if voice.preview_audio_url:
        with contextlib.suppress(Exception):
            await message.reply_audio(
                audio=voice.preview_audio_url,
                caption="🔊 Прослушайте образец, затем выберите голос.",
            )
    await message.reply_text(text, parse_mode="HTML", reply_markup=_voice_markup(state))


async def _begin(update: Any, context: Any, script: str = "") -> None:
    message = update.effective_message or update.callback_query.message
    try:
        avatars, voices = await load_catalog()
    except Exception as exc:
        await message.reply_text(f"⚠️ Не удалось загрузить каталог HeyGen: {type(exc).__name__}: {exc}")
        return
    state = _flow(context)
    state.update({
        "stage": "avatar",
        "avatars": avatars,
        "voices": voices,
        "avatar_index": 0,
        "voice_index": 0,
        "script": _str(script),
    })
    await _show_avatar(message, state)


async def _show_confirmation(message: Any, state: dict[str, Any], user_id: int) -> None:
    avatar, voice, script = _avatar_at(state), _voice_at(state), _str(state.get("script"))
    if not script:
        state["stage"] = "script"
        await message.reply_text(
            "✍️ Пришлите текст, который произнесёт аватар. До 5000 символов.",
            reply_markup=_markup([[_button("Отмена", "hg:cancel")]]),
        )
        return
    _save_preference(user_id, avatar, voice)
    state["stage"] = "confirm"
    await message.reply_text(
        "🎬 <b>Проверьте ролик</b>\n\n"
        f"Образ: <b>{avatar.name}</b>\n"
        f"Голос: <b>{voice.name}</b>\n"
        f"Текст: {script[:900]}",
        parse_mode="HTML",
        reply_markup=_confirm_markup(),
    )


def _new_job(user_id: int, chat_id: int, avatar_id: str, voice_id: str, script: str) -> str:
    _ensure_storage()
    job_id = uuid.uuid4().hex
    now = int(time.time())
    digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
    with _connect() as con:
        con.execute(
            """
            INSERT INTO heygen_avatar_jobs
              (job_id, user_id, chat_id, avatar_id, voice_id, script_sha256, state, created_ts, updated_ts)
            VALUES (?, ?, ?, ?, ?, ?, 'submitting', ?, ?)
            """,
            (job_id, int(user_id), int(chat_id), avatar_id, voice_id, digest, now, now),
        )
    return job_id


def _update_job(job_id: str, state: str, *, video_id: str = "", result_url: str = "", error: str = "") -> None:
    try:
        _ensure_storage()
        with _connect() as con:
            con.execute(
                """
                UPDATE heygen_avatar_jobs
                SET state=?, provider_video_id=COALESCE(NULLIF(?, ''), provider_video_id),
                    result_url=COALESCE(NULLIF(?, ''), result_url),
                    error_text=COALESCE(NULLIF(?, ''), error_text), updated_ts=?
                WHERE job_id=?
                """,
                (state, video_id, result_url, error[:1000], int(time.time()), job_id),
            )
    except Exception:
        return


async def _poll_and_deliver(bot: Any, chat_id: int, job_id: str, video_id: str) -> None:
    from neyrobot_prod.heygen_adapter import poll_presenter_video
    key = _str(os.getenv("HEYGEN_API_KEY"))
    try:
        _update_job(job_id, "polling", video_id=video_id)
        video_url = await poll_presenter_video(key, video_id)
        _update_job(job_id, "completed", result_url=video_url)
        await bot.send_video(chat_id=chat_id, video=video_url, caption="🎬 HeyGen · говорящий аватар · русская речь")
    except Exception as exc:
        _update_job(job_id, "failed", error=f"{type(exc).__name__}: {exc}")
        with contextlib.suppress(Exception):
            await bot.send_message(
                chat_id=chat_id,
                text="⚠️ HeyGen не завершил ролик: " + str(exc)[:350] + ". Повторно не запускайте этот текст до проверки статуса.",
            )


async def _confirm(update: Any, context: Any, state: dict[str, Any]) -> None:
    message = update.callback_query.message
    user, chat = update.effective_user, update.effective_chat
    avatar, voice, script = _avatar_at(state), _voice_at(state), _str(state.get("script"))
    if not script or not user or not chat:
        await message.reply_text("Сценарий не найден. Запустите режим заново.")
        _clear_flow(context)
        return
    key = _str(os.getenv("HEYGEN_API_KEY"))
    if not key:
        await message.reply_text("HeyGen пока не настроен: отсутствует HEYGEN_API_KEY.")
        return
    if len(script) > 5000:
        await message.reply_text("Текст слишком длинный: максимум 5000 символов.")
        return
    if state.get("submitting"):
        await message.reply_text("Этот ролик уже передан HeyGen. Повторный платный запрос заблокирован.")
        return
    state["submitting"] = True
    job_id = _new_job(user.id, chat.id, avatar.avatar_id, voice.voice_id, script)
    await message.reply_text("🎬 HeyGen: отправляю один запрос на создание ролика.")
    try:
        from neyrobot_prod.heygen_adapter import HeyGenValidationError, create_presenter_video
        video_id = await create_presenter_video(
            key, avatar.avatar_id, voice.voice_id, script, idempotency_key=job_id
        )
        _update_job(job_id, "accepted", video_id=video_id)
        await message.reply_text("✅ HeyGen принял ролик. Готовый файл придёт сюда автоматически.")
        _clear_flow(context)
        asyncio.create_task(_poll_and_deliver(context.bot, chat.id, job_id, video_id))
    except HeyGenValidationError as exc:
        # A 4xx is an explicit pre-creation rejection, not an ambiguous paid
        # submission.  Let the user correct the selected assets/text and retry.
        _update_job(job_id, "validation_failed", error=f"{type(exc).__name__}: {exc}")
        state["submitting"] = False
        await message.reply_text(
            "⚠️ HeyGen отклонил запрос до создания ролика: " + str(exc)[:350] +
            ". Можно изменить образ, голос или текст и отправить заново."
        )
    except Exception as exc:
        _update_job(job_id, "uncertain", error=f"{type(exc).__name__}: {exc}")
        await message.reply_text(
            "⚠️ Статус платной отправки HeyGen неясен: " + str(exc)[:350] +
            ". Повторная отправка заблокирована, чтобы не создать дубликат."
        )


async def _command(update: Any, context: Any) -> None:
    await _begin(update, context, " ".join(getattr(context, "args", ()) or ()).strip())


async def _callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    query = update.callback_query
    data = _str(getattr(query, "data", ""))
    if data == "hg:entry:kling":
        await _delegate_to_legacy_avatar(update, context)
        raise ApplicationHandlerStop
    if data.startswith("hg:tv:legacy:"):
        engine = data.rsplit(":", 1)[-1]
        if engine not in {"sora", "kling", "veo", "runway", "seedance"}:
            await query.answer("Неизвестный движок", show_alert=True)
        else:
            await _delegate_to_legacy_text_engine(update, context, engine)
        raise ApplicationHandlerStop

    await query.answer()
    if is_talking_avatar_entry_callback(data):
        await _show_entry_menu(query.message)
        raise ApplicationHandlerStop
    if data in {"act:fun:textvideo", "fun:textvideo"}:
        await _show_video_engine_menu(query.message)
        raise ApplicationHandlerStop
    if data in {"hg:start", "hg:entry:heygen", "hg:tv:heygen"}:
        await _begin(update, context)
        raise ApplicationHandlerStop
    if data == "hg:back:fun":
        await _back_to_fun_menu(update, context)
        raise ApplicationHandlerStop
    state = context.user_data.get(FLOW_KEY)
    if not state:
        await query.message.reply_text("Сессия выбора закончилась. Откройте «Говорящий аватар» ещё раз.")
        raise ApplicationHandlerStop
    if data == "hg:noop":
        raise ApplicationHandlerStop
    if data == "hg:cancel":
        _clear_flow(context)
        await query.message.reply_text("Выбор говорящего аватара отменён.")
        raise ApplicationHandlerStop
    if data == "hg:ap":
        state["avatar_index"] = max(0, int(state.get("avatar_index", 0)) - 1)
        await _show_avatar(query.message, state)
    elif data == "hg:an":
        state["avatar_index"] = min(len(state["avatars"]) - 1, int(state.get("avatar_index", 0)) + 1)
        await _show_avatar(query.message, state)
    elif data == "hg:as":
        state["stage"] = "voice"
        await _show_voice(query.message, state)
    elif data == "hg:vp":
        state["voice_index"] = max(0, int(state.get("voice_index", 0)) - 1)
        await _show_voice(query.message, state)
    elif data == "hg:vn":
        state["voice_index"] = min(len(state["voices"]) - 1, int(state.get("voice_index", 0)) + 1)
        await _show_voice(query.message, state)
    elif data == "hg:voices":
        state["stage"] = "voice"
        await _show_voice(query.message, state)
    elif data == "hg:avatars":
        state["stage"] = "avatar"
        await _show_avatar(query.message, state)
    elif data == "hg:vs":
        await _show_confirmation(query.message, state, update.effective_user.id)
    elif data == "hg:confirm":
        await _confirm(update, context, state)
    raise ApplicationHandlerStop


async def _text_handler(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    state = context.user_data.get(FLOW_KEY)
    if not state or state.get("stage") != "script":
        return
    script = _str(getattr(update.effective_message, "text", ""))
    if not script:
        return
    state["script"] = script
    await _show_confirmation(update.effective_message, state, update.effective_user.id)
    raise ApplicationHandlerStop


def install() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters
    except Exception:
        return
    if getattr(ApplicationBuilder, "_heygen_talking_avatar_v1_hooked", False):
        return
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any) -> Any:
        app = original_build(self, *args, **kwargs)
        if not getattr(app, "_heygen_talking_avatar_v1_handlers", False):
            app.add_handler(CommandHandler("heygen", _command), group=-85)
            app.add_handler(CallbackQueryHandler(_callback, pattern=r"^(?:act:fun:(?:avatar|textvideo)|fun:(?:avatar|textvideo)|hg:)"), group=-85)
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text_handler), group=-85)
            setattr(app, "_heygen_talking_avatar_v1_handlers", True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, "_heygen_talking_avatar_v1_hooked", True)


__all__ = [
    "Avatar", "Voice", "avatar_from_api", "voice_from_api",
    "build_talking_avatar_payload", "selection_key", "is_talking_avatar_entry_callback",
    "video_engine_options", "select_vertical_look", "install",
]
