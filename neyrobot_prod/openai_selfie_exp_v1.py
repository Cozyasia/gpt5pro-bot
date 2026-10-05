# -*- coding: utf-8 -*-
"""Experimental OpenAI celebrity-selfie lane (October 2026).

Completely separate from the frozen V265 production selfie owner.
It edits ONE user photo directly with OpenAI Image API and the existing
owner-managed hero reference catalogue. Removing this module and its single
bootstrap import removes the experiment.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

VERSION = "openai-selfie-exp-v1-2026-10-05"
PREFIX = "oaiselfie:"
_HANDLER_FLAG = "_openai_selfie_exp_v1_bound"
_BUILDER_FLAG = "_openai_selfie_exp_v1_builder"
_INSTALLED = False
_LOG = logging.getLogger("gpt-bot")


def _job_log(job_id: str, event: str, **fields: Any) -> None:
    # IDs, stages and exception classes only. Never record user photos, prompts or keys.
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    _LOG.info("SELFIE_JOB job=%s event=%s %s", job_id, event, details)


def _runtime() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _enabled() -> bool:
    return str(os.environ.get("OPENAI_SELFIE_EXPERIMENT_ENABLED", "1")).strip().lower() not in {"0","false","no","off"}


def _kb(mod: Any, rows):
    return mod.InlineKeyboardMarkup([[mod.InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows])


def _main_kb(mod: Any):
    return _kb(mod, [
        [("📸 Загрузить фото", PREFIX + "photo")],
        [("⭐ Выбрать героя", PREFIX + "countries")],
        [("⬅️ Назад в Развлечения", "mode:fun")],
    ])


def _result_kb(mod: Any):
    return _kb(mod, [
        [("🔁 Повторить с тем же фото", PREFIX + "repeat")],
        [("⭐ Выбрать другого героя", PREFIX + "countries")],
        [("📸 Загрузить другое фото", PREFIX + "photo")],
        [("⬅️ Назад в Развлечения", "mode:fun")],
    ])


def _country_kb(mod: Any):
    from neyrobot_prod import selfie_v208_overlay as catalog
    rows = [[(label, PREFIX + "country:" + code)] for code, (label, _title) in catalog.COUNTRIES.items()]
    rows.append([("⬅️ К началу", PREFIX + "open")])
    return _kb(mod, rows)


def _hero_kb(mod: Any, country: str):
    from neyrobot_prod import celebrity_selfie as base
    rows = [[("⭐ " + str(meta["name"]), PREFIX + "hero:" + slug)]
            for slug, meta in base.CHARACTERS.items() if str(meta.get("country") or "") == country]
    rows.append([("⬅️ К странам", PREFIX + "countries")])
    return _kb(mod, rows)


def _scene_kb(mod: Any):
    from neyrobot_prod import celebrity_selfie as base
    rows = [[(label, PREFIX + "scene:" + key)] for key, (label, _text) in base.SCENES.items()]
    rows.append([("📝 Своя сцена", PREFIX + "scene:custom")])
    rows.append([("⬅️ Другой герой", PREFIX + "countries")])
    return _kb(mod, rows)


def _set_active(context: Any, value: bool = True) -> None:
    context.user_data["openai_selfie_active"] = bool(value)
    if value:
        # Do not activate the legacy cs201/V265 media router.
        context.user_data.pop("cs201_active", None)
        context.user_data.pop("awaiting_ai_selfie_photo", None)


def _clear(context: Any, keep_photo: bool = True) -> None:
    for key in ("openai_selfie_wait_photo", "openai_selfie_wait_scene", "openai_selfie_country",
                "openai_selfie_hero", "openai_selfie_scene", "openai_selfie_wait_scene_photo",
                "openai_selfie_scene_photo", "openai_selfie_scene_ready"):
        context.user_data.pop(key, None)
    if not keep_photo:
        context.user_data.pop("openai_selfie_photo", None)


async def _download_photo(message: Any, trace_id: str = "") -> bytes:
    photos = list(getattr(message, "photo", None) or [])
    doc = getattr(message, "document", None)
    tgfile = None
    if trace_id:
        _job_log(trace_id, "media_get_file_start")
    if photos:
        tgfile = await photos[-1].get_file()
    elif doc is not None and str(getattr(doc, "mime_type", "") or "").startswith("image/"):
        tgfile = await doc.get_file()
    if tgfile is None:
        return b""
    if trace_id:
        _job_log(trace_id, "media_download_start")
    bio = io.BytesIO()
    await tgfile.download_to_memory(out=bio)
    if trace_id:
        _job_log(trace_id, "media_download_done")
    return bio.getvalue()


def _hero_refs(slug: str) -> list[Path]:
    from neyrobot_prod import celebrity_selfie as base
    mod = _runtime()
    return list(base._reference_paths(mod, slug)) if mod is not None else []


def _prompt(hero_name: str, scene: str, custom_scene: bool = False) -> str:
    if custom_scene:
        return (
            "IMAGE 1 is the authoritative SCENE photograph. Preserve its recognizable environment, architecture, "
            "furniture, camera viewpoint and perspective. IMAGE 2 is the authoritative USER identity reference. "
            "Create a realistic photograph placing the user from IMAGE 2 and one second person matching the HERO "
            f"REFERENCE images consistently ({hero_name}) into IMAGE 1. Preserve the user's facial identity with "
            "maximum fidelity: facial geometry, apparent age, eyes, nose, mouth, hairline, skin texture and distinctive "
            "features. Do not preserve the user's original clothing or original background. Choose natural photorealistic "
            "clothing for the user that fits the supplied scene, occasion, weather and social context. Adapt body pose "
            "as needed while keeping identity unmistakable. Match both people to IMAGE 1 lighting, lens perspective, "
            "scale, occlusion and shadows. Keep identities separate; no face merging, averaging or swapping. Exactly "
            "two principal people. No text, watermark or interface elements. The output is an AI-generated fictional fan image."
        )
    return (
        "Use IMAGE 1 as the authoritative USER identity reference. Preserve the user's facial identity with maximum "
        "fidelity: facial geometry, apparent age, eyes, nose, mouth, hairline, skin texture and distinctive features. "
        "The user's original clothing is NOT locked. Choose natural photorealistic clothing appropriate to the requested "
        "scene, occasion, weather and social context. You may adapt pose, framing and background to the requested scene "
        "while keeping the user's identity unmistakable. "
        f"Add one second person matching the HERO REFERENCE images consistently ({hero_name}). Keep the identities "
        "separate; no face merging, averaging or swapping. Exactly two principal people. "
        f"Scene instruction: {scene or 'keep the original location and naturally position the hero beside the user'}. "
        "Use physically plausible scale, perspective, occlusion, shadows and coherent scene lighting. "
        "No text, watermark or interface elements. The output is an AI-generated fictional fan image."
    )

async def _openai_edit(user_photo: bytes, slug: str, scene: str, scene_photo: bytes = b"") -> bytes:
    from neyrobot_prod import celebrity_selfie as base
    key = str(os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing")
    refs = _hero_refs(slug)
    meta = base.CHARACTERS.get(slug) or {}
    required = int(meta.get("required_refs") or 3)
    if len(refs) != required:
        raise RuntimeError(f"hero references={len(refs)}/{required}")
    model = str(os.environ.get("OPENAI_SELFIE_IMAGE_MODEL") or "gpt-image-2.5-sunburst").strip()
    quality = str(os.environ.get("OPENAI_SELFIE_QUALITY") or "high").strip()
    moderation = str(os.environ.get("OPENAI_SELFIE_MODERATION") or "auto").strip()
    custom_scene = len(scene_photo) >= 1024
    prompt = _prompt(str(meta.get("name") or slug), scene, custom_scene=custom_scene)

    files = []
    if custom_scene:
        files.append(("image[]", ("scene.jpg", bytes(scene_photo), "image/jpeg")))
        files.append(("image[]", ("user.jpg", bytes(user_photo), "image/jpeg")))
    else:
        files.append(("image[]", ("user.jpg", bytes(user_photo), "image/jpeg")))
    for i, path in enumerate(refs, 1):
        files.append(("image[]", (f"hero_{i}.jpg", path.read_bytes(), "image/jpeg")))
    data = {"model": model, "prompt": prompt, "quality": quality, "size": "auto", "moderation": moderation, "output_format": "png"}
    timeout_s = max(60.0, float(os.environ.get("OPENAI_SELFIE_TIMEOUT_S", "300") or 300))
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=30.0, write=120.0, read=timeout_s)) as client:
        res = await client.post("https://api.openai.com/v1/images/edits",
                                headers={"Authorization": f"Bearer {key}"},
                                data=data, files=files)
    if res.status_code >= 400:
        detail = res.text[:1000]
        raise RuntimeError(f"OpenAI image edit HTTP {res.status_code}: {detail}")
    payload = res.json()
    items = payload.get("data") or []
    if not items:
        raise RuntimeError("OpenAI image edit returned no image")
    item = items[0] or {}
    b64 = item.get("b64_json")
    if b64:
        out = base64.b64decode(b64)
        if len(out) > 1024:
            return out
    url = item.get("url")
    if url:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            img = await client.get(url)
            img.raise_for_status()
            if len(img.content) > 1024:
                return bytes(img.content)
    raise RuntimeError("OpenAI image edit response contained no usable bytes")


async def _generate(update: Any, context: Any, scene: str, scene_photo: bytes = b"") -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from telegram.error import NetworkError, TimedOut
    mod = _runtime(); msg = getattr(update, "effective_message", None); user = getattr(update, "effective_user", None)
    if mod is None or msg is None or user is None:
        return False
    if context.user_data.get("openai_selfie_job_busy"):
        return False
    photo = bytes(context.user_data.get("openai_selfie_photo") or b"")
    slug = str(context.user_data.get("openai_selfie_hero") or "")
    meta = base.CHARACTERS.get(slug)
    if len(photo) < 1024:
        context.user_data["openai_selfie_wait_photo"] = True
        await msg.reply_text("Сначала пришлите одно исходное фото пользователя.", reply_markup=_main_kb(mod)); return False
    if not meta:
        await msg.reply_text("Сначала выберите героя.", reply_markup=_country_kb(mod)); return False
    if len(_hero_refs(slug)) != int(meta.get("required_refs") or 3):
        await msg.reply_text(f"⚠️ Для «{meta['name']}» не хватает сохранённых референсов героя."); return False

    job_id = uuid.uuid4().hex[:16]
    context.user_data["openai_selfie_job_busy"] = job_id
    started = time.monotonic()
    _job_log(job_id, "accepted", scene_mode="custom" if scene_photo else "preset")

    async def fail(stage: str, exc: Exception) -> None:
        _job_log(job_id, stage, error_type=type(exc).__name__)
        try:
            await msg.reply_text("❌ Не удалось создать изображение. Попробуйте ещё раз.",
                                 reply_markup=_result_kb(mod))
            _job_log(job_id, "terminal", state="FAILURE", delivery="confirmed")
        except Exception as send_exc:
            _job_log(job_id, "terminal", state="FAILURE", delivery="unknown",
                     error_type=type(send_exc).__name__)

    async def action() -> bool:
        try:
            await msg.reply_text("⌛ Бот: создаю селфи с выбранным героем…")
        except Exception as exc:
            _job_log(job_id, "progress_send_failed", error_type=type(exc).__name__)
        _job_log(job_id, "image_request_start", attempt=1)
        try:
            out = await _openai_edit(photo, slug, scene, scene_photo=scene_photo)
        except Exception as exc:
            await fail("image_request_timeout" if isinstance(exc, TimeoutError) or "Timeout" in type(exc).__name__
                       else "image_request_failed", exc)
            return False
        _job_log(job_id, "image_request_complete", output_bytes=len(out),
                 elapsed_ms=round((time.monotonic() - started) * 1000))

        bio = io.BytesIO(out); bio.name = "selfie.png"
        _job_log(job_id, "telegram_delivery_start", attempt=1)
        try:
            delivered = await msg.reply_document(
                document=bio, caption=f"⭐ Селфи со звездой · «{meta['name']}»",
                # PTB's default media upload/response timeouts are short for a PNG.
                write_timeout=180, read_timeout=180, connect_timeout=30, pool_timeout=30,
            )
        except (TimedOut, NetworkError) as exc:
            # Telegram may have accepted the file. A retry or definite failure here
            # can create a second result or a false failure before the first arrives.
            _job_log(job_id, "telegram_delivery_unconfirmed", error_type=type(exc).__name__, retry="none")
            try:
                await msg.reply_text(
                    "⚠️ Изображение создано, но Telegram не подтвердил доставку. "
                    "Проверьте чат через минуту; если файла нет, повторите запрос.",
                    reply_markup=_result_kb(mod),
                )
            except Exception as send_exc:
                _job_log(job_id, "delivery_notice_failed", error_type=type(send_exc).__name__)
            _job_log(job_id, "terminal", state="DELIVERY_UNKNOWN")
            return False
        except Exception as exc:
            await fail("telegram_delivery_failed", exc)
            return False

        _job_log(job_id, "telegram_delivery_confirmed",
                 message_id=getattr(delivered, "message_id", None))
        _job_log(job_id, "terminal", state="SUCCESS",
                 elapsed_ms=round((time.monotonic() - started) * 1000))
        try:
            await msg.reply_text("✅ Можно повторить с тем же фото или выбрать другого героя.",
                                 reply_markup=_result_kb(mod))
        except Exception as exc:
            _job_log(job_id, "controls_send_failed", error_type=type(exc).__name__)
        return True

    runner = getattr(mod, "_try_pay_then_do", None)
    try:
        if callable(runner):
            return bool(await runner(update, context, int(user.id), "img",
                max(0.0, float(getattr(mod, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20)), action,
                remember_kind="openai_selfie_exp_v1",
                remember_payload={"character": slug, "scene": scene, "provider": "openai", "user_refs": 1, "hero_refs": 3},
                silent_failure=True))
        return await action()
    finally:
        if context.user_data.get("openai_selfie_job_busy") == job_id:
            context.user_data.pop("openai_selfie_job_busy", None)


async def callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    mod = _runtime(); q = getattr(update, "callback_query", None)
    if mod is None or q is None:
        return
    data = str(q.data or "")
    if not data.startswith(PREFIX):
        return
    with contextlib.suppress(Exception):
        await q.answer()
    _set_active(context, True)
    cmd = data[len(PREFIX):]
    if cmd == "open":
        _clear(context, keep_photo=True)
        await q.message.reply_text(
            "⭐ Селфи со звездой\n\n"
            "1) загрузите своё фото; 2) выберите героя; 3) выберите сцену.",
            reply_markup=_main_kb(mod))
    elif cmd == "photo":
        _clear(context, keep_photo=False); context.user_data["openai_selfie_wait_photo"] = True
        await q.message.reply_text("📸 Пришлите свою фотографию: селфи или прямой кадр анфас.")
    elif cmd == "repeat":
        if (len(bytes(context.user_data.get("openai_selfie_photo") or b"")) >= 1024
                and context.user_data.get("openai_selfie_hero")):
            context.user_data["openai_selfie_scene_ready"] = True
            await q.message.reply_text("Выберите сцену:", reply_markup=_scene_kb(mod))
        else:
            await q.message.reply_text("Сначала пришлите фотографию и выберите героя.",
                                       reply_markup=_main_kb(mod))
    elif cmd == "countries":
        context.user_data.pop("openai_selfie_scene_ready", None)
        if len(bytes(context.user_data.get("openai_selfie_photo") or b"")) < 1024:
            context.user_data["openai_selfie_wait_photo"] = True
            await q.message.reply_text("Сначала пришлите одно исходное фото.", reply_markup=_main_kb(mod))
        else:
            await q.message.reply_text("⭐ Выберите страну героя:", reply_markup=_country_kb(mod))
    elif cmd.startswith("country:"):
        country = cmd.split(":",1)[1]; context.user_data["openai_selfie_country"] = country
        await q.message.reply_text("⭐ Выберите героя:", reply_markup=_hero_kb(mod, country))
    elif cmd.startswith("hero:"):
        slug = cmd.split(":",1)[1]; meta = base.CHARACTERS.get(slug)
        if not meta:
            await q.message.reply_text("Герой не найден.", reply_markup=_country_kb(mod))
        elif len(_hero_refs(slug)) != int(meta.get("required_refs") or 3):
            await q.message.reply_text(f"⚠️ «{meta['name']}» пока не готов: нужны сохранённые референсы.")
        else:
            context.user_data["openai_selfie_hero"] = slug
            context.user_data["openai_selfie_scene_ready"] = True
            await q.message.reply_text(f"✅ Герой: {meta['name']}. Выберите сцену:", reply_markup=_scene_kb(mod))
    elif cmd.startswith("scene:"):
        if not context.user_data.pop("openai_selfie_scene_ready", False):
            raise ApplicationHandlerStop
        key = cmd.split(":",1)[1]
        if key == "custom":
            context.user_data.pop("openai_selfie_wait_scene", None)
            context.user_data["openai_selfie_wait_scene_photo"] = True
            await q.message.reply_text("🖼 Пришлите фотографию своей сцены. Я сохраню эту локацию и размещу на ней вас и выбранного героя; одежду подберу под сцену автоматически.")
        else:
            preset = base.SCENES.get(key)
            if not preset:
                context.user_data["openai_selfie_scene_ready"] = True
                await q.message.reply_text("Выберите сцену:", reply_markup=_scene_kb(mod))
            else:
                context.user_data["openai_selfie_scene"] = str(preset[1])
                await _generate(update, context, str(preset[1]))
    raise ApplicationHandlerStop


async def media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    if not _enabled() or not context.user_data.get("openai_selfie_active"):
        return
    waiting_user = bool(context.user_data.get("openai_selfie_wait_photo"))
    waiting_scene = bool(context.user_data.get("openai_selfie_wait_scene_photo"))
    if not (waiting_user or waiting_scene):
        return
    trace_id = "media-" + str(getattr(update, "update_id", None) or uuid.uuid4().hex[:12])
    mod = _runtime(); msg = getattr(update, "effective_message", None)
    stage = "download"
    _job_log(trace_id, "media_received", kind="scene" if waiting_scene else "source")
    try:
        if mod is None or msg is None:
            raise RuntimeError("selfie runtime or message unavailable")
        raw = await _download_photo(msg, trace_id=trace_id)
        if len(raw) < 1024:
            _job_log(trace_id, "media_invalid")
            await _media_reply(msg, trace_id, "invalid_photo",
                               "Не удалось прочитать изображение. Пришлите JPEG/PNG как фото или документ.")
        elif waiting_scene:
            context.user_data["openai_selfie_scene_photo"] = raw
            context.user_data.pop("openai_selfie_wait_scene_photo", None)
            _job_log(trace_id, "media_stored", kind="scene")
            await _media_reply(msg, trace_id, "scene_receipt",
                               "✅ Фото сцены принято. Размещаю на ней вас и выбранного героя; одежду адаптирую под обстановку…")
            stage = "generate"
            await _generate(update, context, "Use the supplied custom scene photograph.", scene_photo=raw)
        else:
            stage = "prepare_menu"
            markup = _country_kb(mod)
            context.user_data["openai_selfie_photo"] = raw
            context.user_data.pop("openai_selfie_wait_photo", None)
            _job_log(trace_id, "media_stored", kind="source")
            await _media_reply(msg, trace_id, "source_receipt",
                               "✅ Исходное фото принято. Теперь выберите героя:", reply_markup=markup)
    except Exception as exc:
        _job_log(trace_id, "media_error", stage=stage, error=type(exc).__name__)
        if msg is not None and stage != "generate":
            await _media_reply(msg, trace_id, "media_retry_notice",
                               "Не удалось получить фото. Пришлите его ещё раз.")
    raise ApplicationHandlerStop


async def _media_reply(msg: Any, trace_id: str, event: str, message: str, **kwargs: Any) -> None:
    try:
        await msg.reply_text(message, **kwargs)
        _job_log(trace_id, event, status="sent")
    except Exception as exc:
        # Telegram may have delivered the notice despite a missing response.
        _job_log(trace_id, event, status="unknown", error=type(exc).__name__)


async def text_handler(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    if not _enabled() or not context.user_data.get("openai_selfie_active") or not context.user_data.get("openai_selfie_wait_scene"):
        return
    text = str(getattr(getattr(update, "effective_message", None), "text", "") or "").strip()
    if not text:
        return
    context.user_data.pop("openai_selfie_wait_scene", None)
    context.user_data["openai_selfie_scene"] = text[:1600]
    await _generate(update, context, text[:1600])
    raise ApplicationHandlerStop


async def command(update: Any, context: Any) -> None:
    from neyrobot_prod import celebrity_selfie as base
    mod = _runtime()
    if mod is None:
        return
    _set_active(context, True); _clear(context, keep_photo=True)
    await update.effective_message.reply_text(
        "⭐ Селфи со звездой\n\n"
        "Пришлите своё фото, выберите героя и сцену.",
        reply_markup=_main_kb(mod))


def bind_application(app: Any) -> bool:
    if not _enabled() or app is None or getattr(app, _HANDLER_FLAG, False):
        return bool(app is not None)
    from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters
    # More negative than legacy selfie handlers: this lane owns only its own prefix/state.
    app.add_handler(CommandHandler("selfie_openai", command), group=-7000)
    app.add_handler(CallbackQueryHandler(callback, pattern=r"^oaiselfie:"), group=-7000)
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, media, block=True), group=-6999)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler), group=-6998)
    setattr(app, _HANDLER_FLAG, True)
    return True



_MENU_PATCH_FLAG = "_openai_selfie_menu_patch_v1"

def _promote_openai_selfie(mod: Any, markup: Any, legacy_callbacks: tuple[str, ...]) -> Any:
    rows = []
    found = False
    for row in getattr(markup, "inline_keyboard", ()) or ():
        new_row = []
        for btn in row:
            cb = getattr(btn, "callback_data", None)
            if cb in legacy_callbacks:
                if not found:
                    new_row.append(mod.InlineKeyboardButton("⭐ Селфи со звездой", callback_data=PREFIX + "open"))
                    found = True
                continue
            if cb == PREFIX + "open":
                if not found:
                    new_row.append(mod.InlineKeyboardButton("⭐ Селфи со звездой", callback_data=PREFIX + "open"))
                    found = True
                continue
            new_row.append(btn)
        if new_row:
            rows.append(new_row)
    if not found:
        rows.append([mod.InlineKeyboardButton("⭐ Селфи со звездой", callback_data=PREFIX + "open")])
    return mod.InlineKeyboardMarkup(rows)

def _patch_fun_menus() -> bool:
    mod = _runtime()
    if mod is None or getattr(mod, _MENU_PATCH_FLAG, False):
        return bool(mod is not None)
    original_quick = getattr(mod, "_fun_quick_kb", None)
    if callable(original_quick):
        def openai_fun_quick_kb():
            return _promote_openai_selfie(mod, original_quick(), ("fun:aiselfie",))
        mod._fun_quick_kb = openai_fun_quick_kb
    original_mode = getattr(mod, "_mode_kb", None)
    if callable(original_mode):
        def openai_mode_kb(key: str):
            markup = original_mode(key)
            if key == "fun":
                return _promote_openai_selfie(mod, markup, ("act:fun:aiselfie",))
            return markup
        mod._mode_kb = openai_mode_kb
    setattr(mod, _MENU_PATCH_FLAG, True)
    print("[neyrobot-prod] OpenAI selfie promoted as sole Entertainment selfie route", flush=True)
    return True


def _install_builder_hook() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    from telegram.ext import ApplicationBuilder
    if not getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        previous = ApplicationBuilder.build
        def build(self: Any, *args: Any, **kwargs: Any):
            app = previous(self, *args, **kwargs)
            _patch_fun_menus()
            bind_application(app)
            return app
        ApplicationBuilder.build = build
        setattr(ApplicationBuilder, _BUILDER_FLAG, True)
    _INSTALLED = True


def install() -> None:
    if _enabled():
        _install_builder_hook()


__all__ = ["VERSION", "install", "bind_application", "callback", "media", "text_handler", "command"]
