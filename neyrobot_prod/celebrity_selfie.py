# -*- coding: utf-8 -*-
"""Celebrity Selfie v201: persistent flow, character catalogue and fixed references.

The public workflow is deterministic:
1) receive the user's selfie;
2) choose a configured character;
3) choose a scene;
4) call the existing paid runner.

The first configured character is Roman Abramovich. Generation is enabled only
when exactly three owner-supplied JPEG reference photos are present. Reference
management is available through the hidden owner command /selfie_admin.
"""
from __future__ import annotations

import base64
import contextlib
import json
import os
import sys
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

VERSION = "v201-celebrity-selfie-baseline-2026-07-25"
_PATCH_FLAG = "_CELEBRITY_SELFIE_V201_PATCHED"
_WORKER_STARTED = False
_BUILDER_HOOKED = False
_DIRECT_PROVIDERS = {"gemini", "google", "google-gemini", "gemini-direct", "comet"}

CHARACTERS: dict[str, dict[str, Any]] = {
    "roman_abramovich": {
        "name": "Роман Абрамович",
        "required_refs": 3,
        "aliases": ("роман абрамович", "абрамович", "roman abramovich", "abramovich"),
    },
}

SCENES: dict[str, tuple[str, str]] = {
    "kremlin": ("🏛 В Кремле", "a refined ceremonial interior inspired by the Kremlin, red and gold historic decor, natural smartphone selfie"),
    "yacht": ("🛥 На яхте", "on the deck of a luxury yacht at golden hour, sea in the background, natural smartphone selfie"),
    "stadium": ("⚽ На стадионе", "in a premium football stadium hospitality area, match-day atmosphere, natural smartphone selfie"),
    "office": ("🏢 Деловая встреча", "in an elegant private office during a cordial business meeting, natural smartphone selfie"),
    "restaurant": ("🍽 В ресторане", "in an elegant private restaurant with warm realistic lighting, natural smartphone selfie"),
    "premiere": ("🎬 На премьере", "at a premium film premiere with tasteful event lighting and a discreet red carpet, natural smartphone selfie"),
}


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else default


def _flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() not in {"0", "false", "no", "off"}


def _runtime_module() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _is_owner(mod: Any, user: Any) -> bool:
    uid = int(getattr(user, "id", 0) or 0)
    return bool(uid and uid == int(getattr(mod, "OWNER_ID", 0) or 0))


def _storage_root(mod: Any) -> Path:
    configured = _env("CELEBRITY_SELFIE_DATA_DIR")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    db_path = Path(str(getattr(mod, "DB_PATH", "subs.db") or "subs.db")).resolve()
    candidates.extend([db_path.parent / "celebrity_selfie", Path("/data/celebrity_selfie"), Path("/tmp/celebrity_selfie")])
    for root in candidates:
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return root
        except Exception:
            continue
    return Path("/tmp/celebrity_selfie")


def _character_dir(mod: Any, slug: str) -> Path:
    path = _storage_root(mod) / "characters" / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def _reference_paths(mod: Any, slug: str) -> list[Path]:
    meta = CHARACTERS.get(slug) or {}
    required = int(meta.get("required_refs") or 3)
    root = _character_dir(mod, slug)
    result: list[Path] = []
    for index in range(1, required + 1):
        for ext in ("jpg", "jpeg"):
            path = root / f"{index}.{ext}"
            if path.exists() and path.is_file() and path.stat().st_size > 1024:
                result.append(path)
                break
    return result


def _character_ready(mod: Any, slug: str) -> bool:
    meta = CHARACTERS.get(slug) or {}
    return len(_reference_paths(mod, slug)) == int(meta.get("required_refs") or 3)


def _character_status(mod: Any, slug: str) -> str:
    meta = CHARACTERS.get(slug) or {}
    required = int(meta.get("required_refs") or 3)
    return f"{len(_reference_paths(mod, slug))}/{required} JPEG"


def _save_reference(mod: Any, slug: str, raw: bytes) -> tuple[int, int]:
    meta = CHARACTERS.get(slug)
    if not meta:
        raise ValueError("unknown character")
    required = int(meta.get("required_refs") or 3)
    current = _reference_paths(mod, slug)
    index = min(required, len(current) + 1)
    path = _character_dir(mod, slug) / f"{index}.jpg"
    data = bytes(raw or b"")
    if len(data) < 1024:
        raise ValueError("image is empty")
    try:
        from PIL import Image
        image = Image.open(BytesIO(data)).convert("RGB")
        image.thumbnail((1800, 1800), Image.LANCZOS)
        bio = BytesIO()
        image.save(bio, format="JPEG", quality=94, optimize=True)
        data = bio.getvalue()
    except Exception:
        pass
    path.write_bytes(data)
    return index, required


def _models() -> list[str]:
    values = [_env("GEMINI_IMAGE_MODEL", "gemini-3-pro-image"), _env("GEMINI_IMAGE_FALLBACK_MODEL", "gemini-3.1-flash-image")]
    return list(dict.fromkeys(value for value in values if value))


def _image_size() -> str:
    value = _env("AI_SELFIE_IMAGE_SIZE", "2K").upper()
    return value if value in {"512", "1K", "2K", "4K"} else "2K"


def _aspect_ratio() -> str:
    value = _env("AI_SELFIE_DEFAULT_ASPECT", "4:5")
    allowed = {"1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1", "4:3", "4:5", "5:4", "8:1", "9:16", "16:9", "21:9"}
    return value if value in allowed else "4:5"


def _identity_guard(character_name: str = "the selected public figure") -> str:
    return (
        "IMAGE ROLE RULES: image 1 is the USER identity reference. Images 2, 3 and 4 are three reference photos of the SAME "
        f"selected character, {character_name}. Preserve the user's facial geometry, age, skin tone, eye shape, hairline and distinctive "
        "features from image 1. Reconstruct the second person consistently from all three character references. Keep both people as two "
        "separate recognizable individuals; never merge, average, swap or duplicate their faces. Build a plausible arm's-length smartphone "
        "selfie with consistent lighting, perspective, scale and realistic skin texture. Keep hands anatomically correct. No text, logos, "
        "watermarks or interface elements. The result is a fictional AI-generated fan scene, not evidence of a real meeting or endorsement."
    )


def _prompt(mod: Any, user_prompt: str, preset_prompt: str = "", character_name: str = "") -> str:
    builder = getattr(mod, "_ai_selfie_final_prompt", None)
    base = ""
    if callable(builder):
        with contextlib.suppress(Exception):
            base = str(builder(user_prompt, preset_prompt) or "").strip()
    request = base or (user_prompt or preset_prompt or "realistic smartphone selfie").strip()
    return f"Create one photorealistic smartphone selfie. Scene request: {request[:1200]}. {_identity_guard(character_name)}"


def _extract_b64(value: Any) -> str:
    if isinstance(value, dict):
        if value.get("type") == "image":
            data = value.get("data") or value.get("base64") or value.get("b64_json")
            if isinstance(data, str) and len(data) > 100:
                return data
        for key in ("inlineData", "inline_data", "output_image", "image", "generated_image"):
            item = value.get(key)
            if isinstance(item, dict):
                data = item.get("data") or item.get("base64") or item.get("b64_json")
                if isinstance(data, str) and len(data) > 100:
                    return data
        for key in ("candidates", "content", "parts", "steps", "output", "data", "result", "response"):
            found = _extract_b64(value.get(key))
            if found:
                return found
        for item in value.values():
            found = _extract_b64(item)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _extract_b64(item)
            if found:
                return found
    return ""


def _decode_image(value: Any) -> bytes | None:
    encoded = _extract_b64(value)
    if not encoded:
        return None
    if encoded.startswith("data:") and "," in encoded:
        encoded = encoded.split(",", 1)[1]
    try:
        decoded = base64.b64decode(encoded, validate=False)
    except Exception:
        return None
    return decoded if len(decoded) > 100 else None


def _payload(prompt: str, images: list[tuple[str, str]], *, compatibility: bool) -> dict[str, Any]:
    config: dict[str, Any] = {"responseModalities": ["TEXT", "IMAGE"] if compatibility else ["IMAGE"]}
    if not compatibility:
        config["responseFormat"] = {"image": {"aspectRatio": _aspect_ratio(), "imageSize": _image_size()}}
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for image_b64, mime in images:
        parts.append({"inline_data": {"mime_type": mime, "data": image_b64}})
    return {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}


def _prepare_image(mod: Any, raw: bytes) -> tuple[str, str]:
    prepare = getattr(mod, "_prepare_reference_image_for_gemini", None)
    if not callable(prepare):
        raise RuntimeError("runtime selfie image preprocessor is unavailable")
    result = prepare(raw, int(_env("AI_SELFIE_MAX_SIDE", "1536") or 1536))
    return str(result[0]), str(result[1] or "image/jpeg")


async def generate_direct(mod: Any, image_bytes: bytes, user_prompt: str, preset_prompt: str = "", *, character_slug: str = "") -> bytes:
    key = _env("GEMINI_IMAGE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_IMAGE_API_KEY is missing")
    if not image_bytes:
        raise RuntimeError("selfie image is empty")
    meta = CHARACTERS.get(character_slug) or {}
    character_name = str(meta.get("name") or "selected character")
    refs = _reference_paths(mod, character_slug) if character_slug else []
    required = int(meta.get("required_refs") or 0)
    if character_slug and len(refs) != required:
        raise RuntimeError(f"Для персонажа «{character_name}» загружено {len(refs)} из {required} референсов")

    images = [_prepare_image(mod, image_bytes)]
    for path in refs:
        images.append(_prepare_image(mod, path.read_bytes()))
    prompt = _prompt(mod, user_prompt, preset_prompt, character_name)
    base_url = _env("GEMINI_IMAGE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    timeout_s = max(30.0, float(_env("GEMINI_IMAGE_TIMEOUT_S", "240") or 240))
    deadline = time.monotonic() + timeout_s
    errors: list[str] = []
    headers = {"x-goog-api-key": key, "Accept": "application/json", "Content-Type": "application/json"}

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for model in _models():
            for compatibility in (False, True):
                remaining = deadline - time.monotonic()
                if remaining <= 1:
                    break
                try:
                    response = await client.post(
                        f"{base_url}/models/{model}:generateContent",
                        headers=headers,
                        json=_payload(prompt, images, compatibility=compatibility),
                        timeout=httpx.Timeout(min(remaining, 150.0), connect=20.0, write=90.0, read=min(remaining, 150.0)),
                    )
                except Exception as exc:
                    errors.append(f"{model}: {type(exc).__name__}: {exc}")
                    continue
                if response.status_code >= 400:
                    try:
                        detail = json.dumps(response.json(), ensure_ascii=False)[:700]
                    except Exception:
                        detail = response.text[:700]
                    errors.append(f"{model}: HTTP {response.status_code}: {detail}")
                    continue
                helper = getattr(mod, "_image_bytes_from_response", None)
                if callable(helper):
                    with contextlib.suppress(Exception):
                        output = await helper(response, client)
                        if output:
                            return output
                with contextlib.suppress(Exception):
                    output = _decode_image(response.json())
                    if output:
                        return output
                errors.append(f"{model}: response contained no image")
    raise RuntimeError("Direct Gemini multi-reference edit failed: " + " | ".join(errors[-6:]))


def _kb(mod: Any, rows: list[list[tuple[str, str]]]):
    return mod.InlineKeyboardMarkup([[mod.InlineKeyboardButton(text, callback_data=data) for text, data in row] for row in rows])


def _main_kb(mod: Any):
    return _kb(mod, [
        [("📸 Загрузить своё селфи", "cs201:photo")],
        [("✅ Использовать последнее фото", "cs201:last")],
        [("⭐ Выбрать героя", "cs201:characters")],
        [("⬅️ Назад в Развлечения", "mode:fun")],
    ])


def _character_kb(mod: Any):
    rows = [[(f"⭐ {meta['name']}", f"cs201:character:{slug}")] for slug, meta in CHARACTERS.items()]
    rows.append([("⬅️ К началу", "cs201:open")])
    return _kb(mod, rows)


def _scene_kb(mod: Any):
    rows = [[(label, f"cs201:scene:{key}")] for key, (label, _prompt_text) in SCENES.items()]
    rows.extend([[("📝 Своя сцена", "cs201:scene:custom")], [("⬅️ Выбрать другого героя", "cs201:characters")]])
    return _kb(mod, rows)


def _admin_kb(mod: Any):
    return _kb(mod, [
        [("📤 Загрузить 3 JPEG для Романа Абрамовича", "cs201:admin:upload:roman_abramovich")],
        [("🗑 Очистить референсы", "cs201:admin:clear:roman_abramovich")],
    ])


def _activate(mod: Any, context: Any, user_id: int) -> None:
    context.user_data["cs201_active"] = True
    setter = getattr(mod, "_set_mode_clean", None)
    if callable(setter):
        with contextlib.suppress(Exception):
            setter(int(user_id), "Развлечения", "aiselfie")
    else:
        tracker = getattr(mod, "_mode_track_set", None)
        if callable(tracker):
            with contextlib.suppress(Exception):
                tracker(int(user_id), "aiselfie")


def _active(mod: Any, context: Any, user_id: int) -> bool:
    if bool(context.user_data.get("cs201_active")):
        return True
    getter = getattr(mod, "_mode_track_get", None)
    if callable(getter):
        with contextlib.suppress(Exception):
            if str(getter(int(user_id)) or "").lower() == "aiselfie":
                context.user_data["cs201_active"] = True
                return True
    return bool(context.user_data.get("awaiting_ai_selfie_photo") or context.user_data.get("awaiting_ai_selfie_prompt"))


def _cached_photo(mod: Any, user_id: int) -> bytes:
    getter = getattr(mod, "_get_cached_photo", None)
    if callable(getter):
        with contextlib.suppress(Exception):
            return bytes(getter(int(user_id)) or b"")
    return b""


def _cache_photo(mod: Any, user_id: int, raw: bytes, url: str = "") -> None:
    setter = getattr(mod, "_cache_photo", None)
    if callable(setter):
        with contextlib.suppress(Exception):
            setter(int(user_id), bytes(raw), url or "")


def _clear_generation_state(context: Any, *, keep_active: bool = True) -> None:
    for key in (
        "cs201_character", "cs201_scene", "cs201_wait_custom_scene", "cs201_user_photo_ready",
        "awaiting_ai_selfie_photo", "awaiting_ai_selfie_prompt", "ai_selfie_preset_prompt",
    ):
        context.user_data.pop(key, None)
    if not keep_active:
        context.user_data.pop("cs201_active", None)


async def _show_open(mod: Any, update: Any, context: Any) -> None:
    _activate(mod, context, update.effective_user.id)
    await update.effective_message.reply_text(
        "🤳 AI-селфи со звездой\n\n"
        "Рабочая последовательность: 1) загрузить своё селфи; 2) выбрать героя; 3) выбрать сцену. "
        "Фото, загруженное внутри этого режима, больше не уходит в общее меню обработки.",
        reply_markup=_main_kb(mod),
    )


async def _show_characters(mod: Any, update: Any, context: Any) -> None:
    _activate(mod, context, update.effective_user.id)
    if not _cached_photo(mod, update.effective_user.id):
        context.user_data["awaiting_ai_selfie_photo"] = True
        await update.effective_message.reply_text("Сначала пришлите своё селфи. После загрузки откроется выбор героя.", reply_markup=_main_kb(mod))
        return
    await update.effective_message.reply_text("⭐ Шаг 2/3: выберите героя:", reply_markup=_character_kb(mod))


async def _show_scenes(mod: Any, update: Any, context: Any) -> None:
    slug = str(context.user_data.get("cs201_character") or "")
    meta = CHARACTERS.get(slug)
    if not meta:
        await _show_characters(mod, update, context)
        return
    await update.effective_message.reply_text(f"🎬 Шаг 3/3: выберите сцену для селфи с {meta['name']}:", reply_markup=_scene_kb(mod))


async def _generate(mod: Any, update: Any, context: Any, scene_text: str) -> None:
    slug = str(context.user_data.get("cs201_character") or "")
    meta = CHARACTERS.get(slug)
    if not meta:
        await update.effective_message.reply_text("Сначала выберите героя.", reply_markup=_character_kb(mod))
        return
    if not _character_ready(mod, slug):
        await update.effective_message.reply_text(
            f"⚠️ Герой «{meta['name']}» ещё не подготовлен: требуется 3 JPEG-референса, сейчас {_character_status(mod, slug)}."
        )
        return
    image = _cached_photo(mod, update.effective_user.id)
    if not image:
        context.user_data["awaiting_ai_selfie_photo"] = True
        await update.effective_message.reply_text("Селфи пользователя не найдено. Пришлите его ещё раз.", reply_markup=_main_kb(mod))
        return
    context.user_data["cs201_character"] = slug
    context.user_data["cs201_scene"] = scene_text
    user_prompt = f"Фикционное AI-селфи пользователя с {meta['name']}. Сцена: {scene_text}. Формат {_aspect_ratio()}, реалистичная камера смартфона."
    starter = getattr(mod, "_start_ai_selfie", None)
    if not callable(starter):
        await update.effective_message.reply_text("❌ Платёжный запуск AI-селфи недоступен в этой сборке.")
        return
    await starter(update, context, image, user_prompt, "")


async def callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    mod = _runtime_module()
    query = getattr(update, "callback_query", None)
    if mod is None or query is None:
        return
    data = str(query.data or "")
    try:
        with contextlib.suppress(Exception):
            await query.answer()
        if data in {"cs201:open", "act:fun:aiselfie", "fun:aiselfie"}:
            _clear_generation_state(context, keep_active=False)
            await _show_open(mod, update, context)
            raise ApplicationHandlerStop
        if data in {"cs201:photo", "act:fun:aiselfie_upload"}:
            _activate(mod, context, query.from_user.id)
            context.user_data["awaiting_ai_selfie_photo"] = True
            await query.message.reply_text("📸 Пришлите одно чёткое селфи: лицо полностью видно, без сильного поворота и закрывающих предметов.")
            raise ApplicationHandlerStop
        if data in {"cs201:last", "act:fun:aiselfie_last"}:
            _activate(mod, context, query.from_user.id)
            if not _cached_photo(mod, query.from_user.id):
                context.user_data["awaiting_ai_selfie_photo"] = True
                await query.message.reply_text("Последнего фото нет. Пришлите своё селфи.")
            else:
                context.user_data["cs201_user_photo_ready"] = True
                await _show_characters(mod, update, context)
            raise ApplicationHandlerStop
        if data in {"cs201:characters", "act:fun:aiselfie_custom"} or data.startswith("act:fun:as_preset_"):
            await _show_characters(mod, update, context)
            raise ApplicationHandlerStop
        if data.startswith("cs201:character:"):
            slug = data.rsplit(":", 1)[-1]
            meta = CHARACTERS.get(slug)
            if not meta:
                await _show_characters(mod, update, context)
                raise ApplicationHandlerStop
            context.user_data["cs201_character"] = slug
            if not _character_ready(mod, slug):
                await query.message.reply_text(
                    f"⚠️ «{meta['name']}» пока не активирован: {_character_status(mod, slug)}. Владелец должен загрузить 3 JPEG через /selfie_admin."
                )
                raise ApplicationHandlerStop
            await _show_scenes(mod, update, context)
            raise ApplicationHandlerStop
        if data.startswith("cs201:scene:"):
            scene = data.rsplit(":", 1)[-1]
            if scene == "custom":
                context.user_data["cs201_wait_custom_scene"] = True
                await query.message.reply_text("📝 Опишите только сцену и обстановку. Герой уже выбран.")
            elif scene in SCENES:
                context.user_data["cs201_wait_custom_scene"] = False
                await _generate(mod, update, context, SCENES[scene][1])
            else:
                await _show_scenes(mod, update, context)
            raise ApplicationHandlerStop
        if data.startswith("cs201:admin:"):
            if not _is_owner(mod, query.from_user):
                raise ApplicationHandlerStop
            parts = data.split(":")
            action = parts[2] if len(parts) > 2 else ""
            slug = parts[3] if len(parts) > 3 else "roman_abramovich"
            if action == "upload":
                context.user_data["cs201_admin_upload"] = {"slug": slug}
                await query.message.reply_text("📤 Пришлите три отдельных JPEG-фото героя по одному сообщению. Они сохранятся как референсы 1/3, 2/3 и 3/3.")
            elif action == "clear":
                for path in _character_dir(mod, slug).glob("*.*"):
                    with contextlib.suppress(Exception):
                        path.unlink()
                await query.message.reply_text(f"🗑 Референсы очищены. Статус: {_character_status(mod, slug)}", reply_markup=_admin_kb(mod))
            raise ApplicationHandlerStop
    except ApplicationHandlerStop:
        raise


async def text_entry(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    mod = _runtime_module()
    if mod is None or not getattr(update, "effective_user", None):
        return
    if not _active(mod, context, update.effective_user.id):
        return
    text = str(getattr(update.effective_message, "text", "") or "").strip()
    if not text:
        return
    if context.user_data.get("cs201_wait_custom_scene"):
        context.user_data.pop("cs201_wait_custom_scene", None)
        await _generate(mod, update, context, text)
        raise ApplicationHandlerStop
    slug = str(context.user_data.get("cs201_character") or "")
    if not slug:
        await update.effective_message.reply_text(
            "Сцена получена, но герой ещё не выбран. Сначала выберите героя:",
            reply_markup=_character_kb(mod),
        )
        raise ApplicationHandlerStop
    await _generate(mod, update, context, text)
    raise ApplicationHandlerStop


async def _download_photo_message(message: Any) -> tuple[bytes, str]:
    if getattr(message, "photo", None):
        tg_file = await message.photo[-1].get_file()
        return bytes(await tg_file.download_as_bytearray()), str(getattr(tg_file, "file_path", "") or "")
    document = getattr(message, "document", None)
    mime = str(getattr(document, "mime_type", "") or "").lower()
    filename = str(getattr(document, "file_name", "") or "").lower()
    if document and (mime.startswith("image/") or filename.endswith((".jpg", ".jpeg", ".png", ".webp"))):
        tg_file = await document.get_file()
        return bytes(await tg_file.download_as_bytearray()), str(getattr(tg_file, "file_path", "") or "")
    return b"", ""


async def media_entry(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    mod = _runtime_module()
    user = getattr(update, "effective_user", None)
    message = getattr(update, "message", None)
    if mod is None or user is None or message is None:
        return
    admin_state = context.user_data.get("cs201_admin_upload") or {}
    is_selfie = _active(mod, context, user.id)
    if not admin_state and not is_selfie:
        return
    raw, url = await _download_photo_message(message)
    if not raw:
        return
    if admin_state:
        if not _is_owner(mod, user):
            context.user_data.pop("cs201_admin_upload", None)
            raise ApplicationHandlerStop
        slug = str(admin_state.get("slug") or "roman_abramovich")
        index, required = _save_reference(mod, slug, raw)
        if index >= required:
            context.user_data.pop("cs201_admin_upload", None)
            await message.reply_text(f"✅ Загружены все референсы: {_character_status(mod, slug)}. Герой готов к тесту.", reply_markup=_admin_kb(mod))
        else:
            await message.reply_text(f"✅ Референс {index}/{required} сохранён. Пришлите следующий JPEG.")
        raise ApplicationHandlerStop
    _cache_photo(mod, user.id, raw, url)
    _activate(mod, context, user.id)
    context.user_data.pop("awaiting_ai_selfie_photo", None)
    context.user_data.pop("awaiting_ai_selfie_prompt", None)
    context.user_data["cs201_user_photo_ready"] = True
    await message.reply_text("✅ Селфи пользователя принято. Теперь выберите героя:", reply_markup=_character_kb(mod))
    raise ApplicationHandlerStop


async def admin_command(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    mod = _runtime_module()
    if mod is None or not _is_owner(mod, update.effective_user):
        raise ApplicationHandlerStop
    status = "\n".join(f"• {meta['name']}: {_character_status(mod, slug)}" for slug, meta in CHARACTERS.items())
    await update.effective_message.reply_text(f"🛠 Celebrity Selfie Admin · {VERSION}\n{status}", reply_markup=_admin_kb(mod))
    raise ApplicationHandlerStop


async def diag_command(update: Any, context: Any) -> None:
    mod = _runtime_module()
    if mod is None:
        return
    lines = [
        "🤳 Celebrity Selfie diagnostic",
        f"version={VERSION}",
        f"provider={getattr(mod, 'AI_SELFIE_PROVIDER', _env('AI_SELFIE_PROVIDER', 'gemini'))}",
        f"gemini_key={'on' if bool(_env('GEMINI_IMAGE_API_KEY')) else 'off'}",
        f"storage={_storage_root(mod)}",
        f"active={'on' if _active(mod, context, update.effective_user.id) else 'off'}",
    ]
    for slug in CHARACTERS:
        lines.append(f"character:{slug}={_character_status(mod, slug)} ready={'on' if _character_ready(mod, slug) else 'off'}")
    await update.effective_message.reply_text("\n".join(lines))


def _install_menu_patch(mod: Any) -> None:
    current = getattr(mod, "_ai_selfie_action_kb", None)
    if callable(current) and not getattr(current, "_cs201_menu", False):
        def menu(prefix: str = "act"):
            return _main_kb(mod)
        menu._cs201_menu = True
        menu._cs201_original = current
        mod._ai_selfie_action_kb = menu
    current_text = getattr(mod, "_ai_selfie_menu_text", None)
    if callable(current_text) and not getattr(current_text, "_cs201_menu", False):
        def menu_text() -> str:
            return (
                "🤳 AI-селфи со звездой\n"
                "Последовательный режим: загрузите своё селфи → выберите героя → выберите сцену. "
                "Для каждого героя используются три заранее загруженных JPEG-референса."
            )
        menu_text._cs201_menu = True
        mod._ai_selfie_menu_text = menu_text


def patch_runtime(mod: Any) -> bool:
    current = getattr(mod, "_run_ai_selfie_image", None)
    if not callable(current):
        return False
    _install_menu_patch(mod)
    if getattr(current, "_celebrity_selfie_v201", False):
        mod.AI_SELFIE_RUNTIME_VERSION = VERSION
        setattr(mod, _PATCH_FLAG, True)
        return True
    original = current

    async def run(update: Any, context: Any, image_bytes: bytes, user_prompt: str, preset_prompt: str = "") -> bool:
        provider = str(getattr(mod, "AI_SELFIE_PROVIDER", _env("AI_SELFIE_PROVIDER", "gemini")) or "").strip().lower()
        slug = str(context.user_data.get("cs201_character") or "")
        if provider not in _DIRECT_PROVIDERS or not _env("GEMINI_IMAGE_API_KEY"):
            return bool(await original(update, context, image_bytes, user_prompt, preset_prompt))
        if slug and not _character_ready(mod, slug):
            meta = CHARACTERS.get(slug) or {}
            await update.effective_message.reply_text(f"⚠️ Для «{meta.get('name', slug)}» не хватает референсов: {_character_status(mod, slug)}.")
            return False
        chat_action = getattr(getattr(mod, "ChatAction", None), "UPLOAD_PHOTO", None)
        if chat_action is not None:
            with contextlib.suppress(Exception):
                await context.bot.send_chat_action(update.effective_chat.id, chat_action)
        try:
            await update.effective_message.reply_text("⏳ Создаю AI-селфи по четырём референсам: ваше фото + три фиксированных фото героя…")
            output = await generate_direct(mod, image_bytes, user_prompt, preset_prompt, character_slug=slug)
            bio = BytesIO(output)
            bio.name = "celebrity_selfie.png"
            caption = "🤳 AI-селфи готово ✅\nИзображение сгенерировано ИИ и не подтверждает реальную встречу или поддержку."
            if bool(getattr(mod, "AI_SELFIE_SEND_AS_DOCUMENT", True)):
                input_file = getattr(mod, "InputFile", None)
                await update.effective_message.reply_document(input_file(bio) if callable(input_file) else bio, caption=caption)
            else:
                await update.effective_message.reply_photo(photo=output, caption=caption)
            return True
        except Exception as exc:
            logger = getattr(mod, "log", None)
            if logger:
                with contextlib.suppress(Exception):
                    logger.exception("Celebrity selfie v201 error: %s", exc)
            await update.effective_message.reply_text(f"❌ AI-селфи не получилось. Причина: {str(exc)[:1000]}")
            return False

    run._celebrity_selfie_v201 = True
    run._celebrity_selfie_original = original
    mod._run_ai_selfie_image = run
    mod.AI_SELFIE_RUNTIME_VERSION = VERSION
    mod.CELEBRITY_SELFIE_VERSION = VERSION
    setattr(mod, _PATCH_FLAG, True)
    return True


def install_builder_hook() -> bool:
    global _BUILDER_HOOKED
    if _BUILDER_HOOKED:
        return True
    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters
    except Exception:
        return False
    flag = "_celebrity_selfie_v201_builder"
    if getattr(ApplicationBuilder, flag, False):
        _BUILDER_HOOKED = True
        return True
    original_build = ApplicationBuilder.build
    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, flag, False):
            app.add_handler(CallbackQueryHandler(callback, pattern=r"^(?:cs201:|act:fun:aiselfie|act:fun:as_preset_|fun:aiselfie$)"), group=-30)
            app.add_handler(CommandHandler("selfie_admin", admin_command), group=-30)
            app.add_handler(CommandHandler("diag_selfie", diag_command), group=-30)
            app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, media_entry), group=-29)
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_entry), group=-29)
            setattr(app, flag, True)
        return app
    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, flag, True)
    _BUILDER_HOOKED = True
    return True


def install_async() -> None:
    global _WORKER_STARTED
    install_builder_hook()
    if _WORKER_STARTED or not _flag("AI_SELFIE_DIRECT_GEMINI_ENABLED", True):
        return
    _WORKER_STARTED = True
    def worker() -> None:
        stable = 0
        for _ in range(3600):
            mod = _runtime_module()
            if mod is None:
                time.sleep(0.1)
                continue
            try:
                if patch_runtime(mod):
                    stable += 1
                    if stable >= 300:
                        return
                else:
                    stable = 0
            except Exception:
                stable = 0
            time.sleep(0.1)
    threading.Thread(target=worker, name="neyrobot-celebrity-selfie-v201", daemon=True).start()


__all__ = [
    "VERSION", "CHARACTERS", "SCENES", "generate_direct", "patch_runtime", "install_builder_hook", "install_async",
    "_character_ready", "_reference_paths", "_payload",
]
