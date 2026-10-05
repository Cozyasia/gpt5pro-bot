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
import os
import sys
from pathlib import Path
from typing import Any

import httpx

VERSION = "openai-selfie-exp-v1-2026-10-05"
PREFIX = "oaiselfie:"
_HANDLER_FLAG = "_openai_selfie_exp_v1_bound"
_BUILDER_FLAG = "_openai_selfie_exp_v1_builder"
_INSTALLED = False


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
                "openai_selfie_hero", "openai_selfie_scene"):
        context.user_data.pop(key, None)
    if not keep_photo:
        context.user_data.pop("openai_selfie_photo", None)


async def _download_photo(message: Any) -> bytes:
    photos = list(getattr(message, "photo", None) or [])
    doc = getattr(message, "document", None)
    tgfile = None
    if photos:
        tgfile = await photos[-1].get_file()
    elif doc is not None and str(getattr(doc, "mime_type", "") or "").startswith("image/"):
        tgfile = await doc.get_file()
    if tgfile is None:
        return b""
    bio = io.BytesIO()
    await tgfile.download_to_memory(out=bio)
    return bio.getvalue()


def _hero_refs(slug: str) -> list[Path]:
    from neyrobot_prod import celebrity_selfie as base
    mod = _runtime()
    return list(base._reference_paths(mod, slug)) if mod is not None else []


def _prompt(hero_name: str, scene: str) -> str:
    return (
        "Edit IMAGE 1 rather than recreating it. IMAGE 1 is the authoritative original user photograph. "
        "Preserve the user already present in IMAGE 1 with maximum fidelity: face, identity, apparent age, "
        "expression, hair, skin texture, body, clothing, pose, hands, camera angle, lens perspective, crop, "
        "background, furniture and lighting. Do not beautify, redraw, replace, move or restyle that person. "
        f"Add one second person matching the HERO REFERENCE images consistently ({hero_name}). "
        "Place the added person naturally in available space beside the user, with physically plausible scale, "
        "occlusion, perspective, shadows and scene lighting. Keep the two identities separate; no face merging, "
        "averaging or swapping. Exactly two principal people. "
        f"Scene instruction: {scene or 'keep the original location and naturally seat/position the hero beside the user'}. "
        "If the scene instruction conflicts with preservation of IMAGE 1, preservation of IMAGE 1 wins. "
        "No text, watermark or interface elements. The output is an AI-generated fictional fan image."
    )


async def _openai_edit(user_photo: bytes, slug: str, scene: str) -> bytes:
    from neyrobot_prod import celebrity_selfie as base
    key = str(os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing")
    refs = _hero_refs(slug)
    meta = base.CHARACTERS.get(slug) or {}
    required = int(meta.get("required_refs") or 3)
    if len(refs) != required:
        raise RuntimeError(f"hero references={len(refs)}/{required}")
    model = str(os.environ.get("OPENAI_SELFIE_IMAGE_MODEL") or "gpt-image-1.5").strip()
    quality = str(os.environ.get("OPENAI_SELFIE_QUALITY") or "high").strip()
    moderation = str(os.environ.get("OPENAI_SELFIE_MODERATION") or "auto").strip()
    prompt = _prompt(str(meta.get("name") or slug), scene)

    files = [("image[]", ("user.jpg", bytes(user_photo), "image/jpeg"))]
    for i, path in enumerate(refs, 1):
        files.append(("image[]", (f"hero_{i}.jpg", path.read_bytes(), "image/jpeg")))
    data = {"model": model, "prompt": prompt, "quality": quality, "size": "auto", "moderation": moderation}
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


async def _generate(update: Any, context: Any, scene: str) -> bool:
    from neyrobot_prod import celebrity_selfie as base
    mod = _runtime(); msg = getattr(update, "effective_message", None); user = getattr(update, "effective_user", None)
    if mod is None or msg is None or user is None:
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

    async def action() -> bool:
        try:
            await msg.reply_text("⏳ OpenAI: редактирую исходное фото и добавляю выбранного героя…")
            out = await _openai_edit(photo, slug, scene)
            bio = io.BytesIO(out); bio.name = "openai_selfie.png"
            await msg.reply_document(document=bio,
                caption=f"⭐ Селфи со звездой OpenAI · «{meta['name']}»\nЭкспериментальный отдельный маршрут. Исходный режим V265 не использовался.")
            await msg.reply_text("✅ Можно повторить с тем же фото или выбрать другого героя.", reply_markup=_main_kb(mod))
            return True
        except Exception as exc:
            await msg.reply_text(f"❌ OpenAI-режим не создал изображение. Старый режим не затронут.\n{type(exc).__name__}: {str(exc)[:800]}")
            return False

    runner = getattr(mod, "_try_pay_then_do", None)
    if callable(runner):
        return bool(await runner(update, context, int(user.id), "img",
            max(0.0, float(getattr(mod, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20)), action,
            remember_kind="openai_selfie_exp_v1",
            remember_payload={"character": slug, "scene": scene, "provider": "openai", "user_refs": 1, "hero_refs": 3}))
    return await action()


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
            "⭐ Селфи со звездой OpenAI — эксперимент\n\n"
            "1) одно исходное фото пользователя; 2) герой; 3) сцена. "
            "OpenAI редактирует исходную фотографию напрямую. Текущий V265 остаётся отдельным режимом.",
            reply_markup=_main_kb(mod))
    elif cmd == "photo":
        _clear(context, keep_photo=False); context.user_data["openai_selfie_wait_photo"] = True
        await q.message.reply_text("📸 Пришлите одно исходное фото. Желательно оставить свободное место рядом с собой.")
    elif cmd == "countries":
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
            await q.message.reply_text(f"✅ Герой: {meta['name']}. Выберите сцену:", reply_markup=_scene_kb(mod))
    elif cmd.startswith("scene:"):
        key = cmd.split(":",1)[1]
        if key == "custom":
            context.user_data["openai_selfie_wait_scene"] = True
            await q.message.reply_text("📝 Опишите, как добавить героя к вашему исходному фото.")
        else:
            preset = base.SCENES.get(key)
            if not preset:
                await q.message.reply_text("Выберите сцену:", reply_markup=_scene_kb(mod))
            else:
                context.user_data["openai_selfie_scene"] = str(preset[1])
                await _generate(update, context, str(preset[1]))
    raise ApplicationHandlerStop


async def media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    if not _enabled() or not context.user_data.get("openai_selfie_active") or not context.user_data.get("openai_selfie_wait_photo"):
        return
    mod = _runtime(); msg = getattr(update, "effective_message", None)
    if mod is None or msg is None:
        return
    raw = await _download_photo(msg)
    if len(raw) < 1024:
        await msg.reply_text("Не удалось прочитать изображение. Пришлите JPEG/PNG как фото или документ.")
    else:
        context.user_data["openai_selfie_photo"] = raw
        context.user_data.pop("openai_selfie_wait_photo", None)
        await msg.reply_text("✅ Исходное фото принято. Теперь выберите героя:", reply_markup=_country_kb(mod))
    raise ApplicationHandlerStop


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
        "⭐ Селфи со звездой OpenAI — эксперимент\n\n"
        "Отдельный direct-edit маршрут. Одно фото пользователя + референсы выбранного героя.",
        reply_markup=_main_kb(mod))


def bind_application(app: Any) -> bool:
    if not _enabled() or app is None or getattr(app, _HANDLER_FLAG, False):
        return bool(app is not None)
    from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters
    # More negative than legacy selfie handlers: this lane owns only its own prefix/state.
    app.add_handler(CommandHandler("selfie_openai", command), group=-7000)
    app.add_handler(CallbackQueryHandler(callback, pattern=r"^oaiselfie:"), group=-7000)
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, media), group=-6999)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler), group=-6998)
    setattr(app, _HANDLER_FLAG, True)
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
            bind_application(app)
            return app
        ApplicationBuilder.build = build
        setattr(ApplicationBuilder, _BUILDER_FLAG, True)
    _INSTALLED = True


def install() -> None:
    if _enabled():
        _install_builder_hook()


__all__ = ["VERSION", "install", "bind_application", "callback", "media", "text_handler", "command"]
