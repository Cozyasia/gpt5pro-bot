# -*- coding: utf-8 -*-
"""V208 overlay: two user selfies, country catalogue, 5-reference Comet route."""
from __future__ import annotations

import contextlib
import os
import re
import sys
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any

VERSION = "v208-selfie-dual-reference-country-catalog-2026-07-26"
COUNTRIES = {
    "ru": ("🇷🇺 Русские герои", "Русские герои"),
    "us": ("🇺🇸 Американские герои", "Американские герои"),
}
CHARACTERS = {
    "roman_abramovich": {"name": "Роман Абрамович", "country": "ru", "required_refs": 3, "aliases": ("роман абрамович", "абрамович", "roman abramovich")},
    "vlad_a4_bumaga": {"name": "Влад А4 (Бумага)", "country": "ru", "required_refs": 3, "aliases": ("влад а4", "а4 бумага", "vlad a4")},
    "egor_kreed": {"name": "Егор Крид", "country": "ru", "required_refs": 3, "aliases": ("егор крид", "крид", "egor kreed")},
    "olga_buzova": {"name": "Ольга Бузова", "country": "ru", "required_refs": 3, "aliases": ("ольга бузова", "бузова", "olga buzova")},
    "dima_maslennikov": {"name": "Дима Масленников", "country": "ru", "required_refs": 3, "aliases": ("дима масленников", "масленников", "dima maslennikov")},
    "mikhail_galustyan": {"name": "Михаил Галустян", "country": "ru", "required_refs": 3, "aliases": ("михаил галустян", "галустян", "mikhail galustyan")},
    "basta": {"name": "Баста", "country": "ru", "required_refs": 3, "aliases": ("баста", "василий вакуленко", "basta")},
    "pavel_volya": {"name": "Павел Воля", "country": "ru", "required_refs": 3, "aliases": ("павел воля", "воля", "pavel volya")},
    "timati": {"name": "Тимати", "country": "ru", "required_refs": 3, "aliases": ("тимати", "тимур юнусов", "timati")},
    "sergey_bezrukov": {"name": "Сергей Безруков", "country": "ru", "required_refs": 3, "aliases": ("сергей безруков", "безруков", "sergey bezrukov")},
    "mrbeast": {"name": "MrBeast", "country": "us", "required_refs": 3, "aliases": ("mrbeast", "мистер бист", "jimmy donaldson")},
    "elon_musk": {"name": "Илон Маск", "country": "us", "required_refs": 3, "aliases": ("илон маск", "elon musk")},
    "dwayne_johnson": {"name": "Дуэйн Джонсон", "country": "us", "required_refs": 3, "aliases": ("дуэйн джонсон", "скала", "dwayne johnson")},
    "taylor_swift": {"name": "Тейлор Свифт", "country": "us", "required_refs": 3, "aliases": ("тейлор свифт", "taylor swift")},
    "billie_eilish": {"name": "Билли Айлиш", "country": "us", "required_refs": 3, "aliases": ("билли айлиш", "billie eilish")},
    "ariana_grande": {"name": "Ариана Гранде", "country": "us", "required_refs": 3, "aliases": ("ариана гранде", "ariana grande")},
    "selena_gomez": {"name": "Селена Гомес", "country": "us", "required_refs": 3, "aliases": ("селена гомес", "selena gomez")},
    "kim_kardashian": {"name": "Ким Кардашьян", "country": "us", "required_refs": 3, "aliases": ("ким кардашьян", "kim kardashian")},
    "kylie_jenner": {"name": "Кайли Дженнер", "country": "us", "required_refs": 3, "aliases": ("кайли дженнер", "kylie jenner")},
    "will_smith": {"name": "Уилл Смит", "country": "us", "required_refs": 3, "aliases": ("уилл смит", "will smith")},
}
MODE_LABELS = {
    "учёба": ("study", "Учёба"), "учеба": ("study", "Учёба"),
    "работа/бизнес": ("work", "Работа/Бизнес"), "работа и бизнес": ("work", "Работа/Бизнес"),
    "развлечения": ("fun", "Развлечения"), "медицина": ("medicine", "Медицина"),
    "движки": ("engines", "Движки"), "баланс": ("billing", "Баланс/подписка"),
    "баланс/подписка": ("billing", "Баланс/подписка"),
}
_STARTED = False
_BUILDER = False


def _runtime() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "BOT_TOKEN"):
            return mod
    return None


def _photos(context: Any) -> list[bytes]:
    out = []
    for item in context.user_data.get("cs201_user_photos") or []:
        raw = bytes(item or b"")
        if len(raw) > 1024:
            out.append(raw)
    return out[:2]


def _reset_photos(context: Any, first: bytes | None = None) -> None:
    values = [bytes(first)] if first and len(bytes(first)) > 1024 else []
    context.user_data["cs201_user_photos"] = values
    context.user_data["cs201_user_photo_step"] = len(values)


def _append_photo(context: Any, raw: bytes) -> int:
    values = _photos(context)
    if len(values) >= 2:
        values = []
    data = bytes(raw or b"")
    if len(data) < 1024:
        raise ValueError("empty selfie")
    values.append(data)
    context.user_data["cs201_user_photos"] = values
    context.user_data["cs201_user_photo_step"] = len(values)
    context.user_data["cs201_user_photo_ready"] = len(values) == 2
    return len(values)


def _clear(context: Any, *, keep_photos: bool = True) -> None:
    keys = ("cs201_active", "cs201_character", "cs201_country", "cs201_scene", "cs201_wait_custom_scene",
            "cs201_user_photo_ready", "awaiting_ai_selfie_photo", "awaiting_ai_selfie_prompt", "ai_selfie_preset_prompt")
    for key in keys:
        context.user_data.pop(key, None)
    if not keep_photos:
        context.user_data.pop("cs201_user_photos", None)
        context.user_data.pop("cs201_user_photo_step", None)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"^[^0-9A-Za-zА-Яа-яЁё]+", "", str(text or "").strip()).strip()).casefold()


def _mode(text: str) -> tuple[str, str] | None:
    return MODE_LABELS.get(_normalise(text))


def _country_kb(base: Any, mod: Any):
    rows = [[(label, f"cs201:country:{code}")] for code, (label, _title) in COUNTRIES.items()]
    rows.append([("⬅️ К началу", "cs201:open")])
    return base._kb(mod, rows)


def _character_kb(base: Any, mod: Any, country: str):
    rows = [[(f"⭐ {meta['name']}", f"cs201:character:{slug}")]
            for slug, meta in base.CHARACTERS.items() if meta.get("country") == country]
    rows.append([("⬅️ К странам", "cs201:characters")])
    return base._kb(mod, rows)


async def _public_callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    mod = _runtime(); q = getattr(update, "callback_query", None)
    if mod is None or q is None:
        return
    data = str(q.data or "")
    with contextlib.suppress(Exception):
        await q.answer()
    if data in {"cs201:open", "act:fun:aiselfie", "fun:aiselfie"}:
        _clear(context, keep_photos=True); base._activate(mod, context, q.from_user.id)
        await q.message.reply_text("🤳 AI-селфи со звездой\n\n1) два селфи пользователя; 2) страна и герой; 3) сцена. Три JPEG героя хранятся на Persistent Disk.", reply_markup=base._main_kb(mod))
    elif data in {"cs201:photo", "act:fun:aiselfie_upload"}:
        base._activate(mod, context, q.from_user.id); _reset_photos(context); context.user_data["awaiting_ai_selfie_photo"] = True
        await q.message.reply_text("📸 Селфи 1/2: пришлите чёткое фото анфас без фильтров.")
    elif data in {"cs201:last", "act:fun:aiselfie_last"}:
        base._activate(mod, context, q.from_user.id); cached = base._cached_photo(mod, q.from_user.id)
        _reset_photos(context, cached if cached else None); context.user_data["awaiting_ai_selfie_photo"] = True
        await q.message.reply_text("✅ Последнее фото — селфи 1/2. Пришлите селфи 2/2 с поворотом головы 15–30°." if cached else "Последнего фото нет. Пришлите селфи 1/2 анфас.")
    elif data in {"cs201:characters", "act:fun:aiselfie_custom"} or data.startswith("act:fun:as_preset_"):
        base._activate(mod, context, q.from_user.id)
        if len(_photos(context)) != 2:
            context.user_data["awaiting_ai_selfie_photo"] = True
            await q.message.reply_text("Сначала пришлите два селфи пользователя.", reply_markup=base._main_kb(mod))
        else:
            await q.message.reply_text("⭐ Выберите страну героя:", reply_markup=_country_kb(base, mod))
    elif data.startswith("cs201:country:"):
        country = data.rsplit(":", 1)[-1]
        if country not in COUNTRIES:
            await q.message.reply_text("Выберите страну:", reply_markup=_country_kb(base, mod))
        else:
            context.user_data["cs201_country"] = country
            await q.message.reply_text(f"⭐ {COUNTRIES[country][1]}: выберите имя героя:", reply_markup=_character_kb(base, mod, country))
    elif data.startswith("cs201:character:"):
        slug = data.rsplit(":", 1)[-1]; meta = base.CHARACTERS.get(slug)
        if not meta:
            await q.message.reply_text("Выберите страну:", reply_markup=_country_kb(base, mod))
        elif not base._character_ready(mod, slug):
            await q.message.reply_text(f"⚠️ «{meta['name']}» пока не активирован: {base._character_status(mod, slug)}. Загрузите 3 JPEG через /selfie_admin.")
        else:
            context.user_data["cs201_character"] = slug; context.user_data["cs201_country"] = meta.get("country")
            await base._show_scenes(mod, update, context)
    elif data.startswith("cs201:scene:"):
        scene = data.rsplit(":", 1)[-1]
        if scene == "custom":
            context.user_data["cs201_wait_custom_scene"] = True
            await q.message.reply_text("📝 Опишите сцену и обстановку. Герой уже выбран.")
        elif scene in base.SCENES:
            context.user_data.pop("cs201_wait_custom_scene", None)
            await base._generate(mod, update, context, base.SCENES[scene][1])
        else:
            await base._show_scenes(mod, update, context)
    else:
        return
    raise ApplicationHandlerStop


async def _public_media(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    mod = _runtime(); user = getattr(update, "effective_user", None); msg = getattr(update, "effective_message", None)
    if mod is None or user is None or msg is None or not base._active(mod, context, user.id):
        return
    raw, url = await base._download_photo_message(msg)
    if not raw:
        return
    base._activate(mod, context, user.id); count = _append_photo(context, raw); base._cache_photo(mod, user.id, raw, url)
    if count == 1:
        context.user_data["awaiting_ai_selfie_photo"] = True
        await msg.reply_text("✅ Селфи 1/2 принято. Теперь пришлите селфи 2/2 с лёгким поворотом головы.")
    else:
        context.user_data.pop("awaiting_ai_selfie_photo", None)
        await msg.reply_text("✅ Селфи 2/2 принято. Выберите страну героя:", reply_markup=_country_kb(base, mod))
    raise ApplicationHandlerStop


async def _public_text(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    mod = _runtime(); user = getattr(update, "effective_user", None); msg = getattr(update, "effective_message", None)
    if mod is None or user is None or msg is None or not base._active(mod, context, user.id):
        return
    text = str(getattr(msg, "text", "") or "").strip()
    if _mode(text):
        _clear(context, keep_photos=True); return
    if context.user_data.get("cs201_wait_custom_scene"):
        context.user_data.pop("cs201_wait_custom_scene", None); await base._generate(mod, update, context, text)
    elif not context.user_data.get("cs201_character"):
        await msg.reply_text("Сначала выберите страну и героя:", reply_markup=_country_kb(base, mod))
    else:
        await base._generate(mod, update, context, text)
    raise ApplicationHandlerStop


async def _comet_generate(user_images: list[bytes], slug: str, scene: str) -> bytes:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as gen
    mod = _runtime(); refs = base._reference_paths(mod, slug)
    if len(user_images) != 2 or len(refs) != 3:
        raise RuntimeError(f"user selfies={len(user_images)}/2, character refs={len(refs)}/3")
    prepared = [base._prepare_image(mod, raw) for raw in user_images]
    prepared.extend(base._prepare_image(mod, path.read_bytes()) for path in refs)
    meta = base.CHARACTERS.get(slug) or {}; name = str(meta.get("name") or slug)
    prompt = ("Create one photorealistic vertical smartphone selfie with exactly two people. "
              f"Scene: {scene}. Aspect ratio {base._aspect_ratio()}. REFERENCES 1 and 2 are the SAME USER from different angles; preserve identity exactly. "
              f"REFERENCES 3, 4 and 5 are the SAME second person, {name}; reconstruct identity from all three. "
              "Never merge, average, substitute, beautify or duplicate faces. Natural lighting, perspective, skin and correct anatomy. No text or watermark. Fictional AI scene.")
    key = gen._comet_key(); base_url = (os.environ.get("COMET_BASE_URL") or "https://api.cometapi.com").rstrip("/")
    if not key:
        raise RuntimeError("COMET_API_KEY is missing")
    headers = {"Authorization": f"Bearer {key}", "x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}
    import httpx
    errors = []
    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(max(60.0, float(os.environ.get("COMET_SELFIE_TIMEOUT_S", "300"))), connect=25.0)) as client:
        for model in gen._models():
            for camel, compat in ((True, False), (False, False), (True, True), (False, True)):
                labels = ("REFERENCE 1 — USER SELFIE A", "REFERENCE 2 — USER SELFIE B", "REFERENCE 3 — CHARACTER A", "REFERENCE 4 — CHARACTER B", "REFERENCE 5 — CHARACTER C")
                parts = [{"text": prompt}]
                for label, (data, mime) in zip(labels, prepared):
                    parts.append({"text": label})
                    parts.append({"inlineData": {"mimeType": mime, "data": data}} if camel else {"inline_data": {"mime_type": mime, "data": data}})
                config = {"responseModalities": ["TEXT", "IMAGE"]}
                if not compat:
                    config["imageConfig"] = {"aspectRatio": base._aspect_ratio(), "imageSize": base._image_size()}
                try:
                    res = await client.post(f"{base_url}/v1beta/models/{model}:generateContent", headers=headers, json={"contents": [{"role": "user", "parts": parts}], "generationConfig": config})
                    if res.status_code >= 400:
                        errors.append(f"{model}: HTTP {res.status_code}: {res.text[:300]}")
                        continue
                    out = gen._extract_final_image(res.json())
                    if out:
                        return out
                except Exception as exc:
                    errors.append(f"{model}: {type(exc).__name__}: {exc}")
    raise RuntimeError("Comet five-reference generation failed: " + " | ".join(errors[-6:]))


async def _generate(update: Any, context: Any, scene: str) -> None:
    from neyrobot_prod import celebrity_selfie as base
    mod = _runtime(); slug = str(context.user_data.get("cs201_character") or ""); meta = base.CHARACTERS.get(slug); photos = _photos(context)
    if not meta:
        await update.effective_message.reply_text("Сначала выберите страну и героя.", reply_markup=_country_kb(base, mod)); return
    if not base._character_ready(mod, slug):
        await update.effective_message.reply_text(f"⚠️ Для «{meta['name']}» не хватает референсов: {base._character_status(mod, slug)}."); return
    if len(photos) != 2:
        context.user_data["awaiting_ai_selfie_photo"] = True; await update.effective_message.reply_text("Нужны два селфи пользователя.", reply_markup=base._main_kb(mod)); return
    runner = getattr(mod, "_try_pay_then_do", None)
    if not callable(runner):
        await update.effective_message.reply_text("❌ Платёжный guard генераций не найден."); return

    async def action() -> bool:
        try:
            await update.effective_message.reply_text("⏳ Создаю AI-селфи: 2 селфи пользователя + 3 JPEG героя.")
            output = await _comet_generate(photos, slug, scene); bio = BytesIO(output); bio.name = "celebrity_selfie_v208.png"
            caption = f"🤳 AI-селфи с персонажем «{meta['name']}» готово ✅\nМаршрут: CometAPI / Gemini, 5 референсов. Изображение сгенерировано ИИ."
            if bool(getattr(mod, "AI_SELFIE_SEND_AS_DOCUMENT", True)):
                cls = getattr(mod, "InputFile", None); await update.effective_message.reply_document(cls(bio) if callable(cls) else bio, caption=caption)
            else:
                await update.effective_message.reply_photo(photo=output, caption=caption)
            _clear(context, keep_photos=True)
            setter = getattr(mod, "_set_mode_clean", None)
            if callable(setter):
                setter(int(update.effective_user.id), "Развлечения", "")
            return True
        except Exception as exc:
            await update.effective_message.reply_text(f"❌ AI-селфи не создано; средства не должны списываться. Причина: {str(exc)[:1000]}")
            return False

    await runner(update, context, update.effective_user.id, "img", max(0.0, float(getattr(mod, "AI_SELFIE_UNIT_COST_USD", 0.20) or 0.20)), action,
                 remember_kind="celebrity_selfie_v208", remember_payload={"character": slug, "scene": scene, "references": 5, "provider": "comet"})


def _admin_catalog(storage: Any, mod: Any):
    return mod.InlineKeyboardMarkup([
        [mod.InlineKeyboardButton("🇷🇺 Русские герои", callback_data="ss208:country:ru")],
        [mod.InlineKeyboardButton("🇺🇸 Американские герои", callback_data="ss208:country:us")],
        [mod.InlineKeyboardButton("⬅️ В AI-селфи", callback_data="cs201:open")],
    ])


def _admin_country(storage: Any, mod: Any, country: str):
    from neyrobot_prod import celebrity_selfie as base
    rows = [[mod.InlineKeyboardButton(f"{'✅' if base._character_ready(mod, slug) else '⬜'} {meta['name']} · {base._character_status(mod, slug)}", callback_data=f"ss208:hero:{slug}")]
            for slug, meta in base.CHARACTERS.items() if meta.get("country") == country]
    rows.append([mod.InlineKeyboardButton("⬅️ К странам", callback_data="ss208:catalog")])
    return mod.InlineKeyboardMarkup(rows)


async def _diag_storage(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    mod = _runtime()
    try:
        if mod is None:
            return
        root = base._storage_root(mod)
        lines = ["💾 Selfie Storage diagnostic", f"version={VERSION}", f"storage={root}",
                 f"data_is_mount={'on' if os.path.ismount('/data') else 'off'}", "persistent_storage=on",
                 f"characters={len(base.CHARACTERS)}", "generator=v208-comet-five-reference", "user_references=2", "hero_references=3", "references_per_request=5"]
        for slug in base.CHARACTERS:
            lines.append(f"{slug}={base._character_status(mod, slug)} ready={'on' if base._character_ready(mod, slug) else 'off'}")
        await update.effective_message.reply_text("\n".join(lines))
    finally:
        raise ApplicationHandlerStop


async def _admin_command(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import selfie_storage_v205 as storage
    mod = _runtime()
    try:
        if mod is None or not storage._authorized(mod, update.effective_user):
            await update.effective_message.reply_text("⛔ Сервисное меню недоступно.")
            return
        await update.effective_message.reply_text(f"🛠 Каталог AI-селфи · {VERSION}\nХранилище: {storage.storage_root(mod)}\nВыберите страну, затем имя героя:", reply_markup=_admin_catalog(storage, mod))
    finally:
        raise ApplicationHandlerStop


async def _admin_callback(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import selfie_storage_v205 as storage
    mod = _runtime(); q = getattr(update, "callback_query", None)
    try:
        if mod is None or q is None or not storage._authorized(mod, q.from_user):
            return
        with contextlib.suppress(Exception):
            await q.answer()
        data = str(q.data or "")
        if data == "ss208:catalog":
            await q.message.reply_text("Выберите страну:", reply_markup=_admin_catalog(storage, mod)); return
        if data.startswith("ss208:country:"):
            country = data.rsplit(":", 1)[-1]
            await q.message.reply_text(COUNTRIES.get(country, ("Герои",))[0], reply_markup=_admin_country(storage, mod, country)); return
        if data.startswith("ss208:hero:"):
            slug = data.rsplit(":", 1)[-1]; meta = base.CHARACTERS.get(slug)
            if not meta:
                return
            kb = mod.InlineKeyboardMarkup([
                [mod.InlineKeyboardButton(f"📥 Загрузить 3 JPEG · {meta['name']}", callback_data=f"ss208:upload:{slug}")],
                [mod.InlineKeyboardButton("📊 Проверить статус", callback_data=f"ss208:status:{slug}")],
                [mod.InlineKeyboardButton("🗑 Очистить референсы", callback_data=f"ss208:clear:{slug}")],
                [mod.InlineKeyboardButton("⬅️ К списку страны", callback_data=f"ss208:country:{meta['country']}")],
            ])
            await q.message.reply_text(f"📊 {meta['name']}: {base._character_status(mod, slug)}\nХранилище: {base._character_dir(mod, slug)}", reply_markup=kb); return
        for action in ("upload", "status", "clear"):
            prefix = f"ss208:{action}:"
            if data.startswith(prefix):
                slug = data[len(prefix):]; meta = base.CHARACTERS.get(slug)
                if not meta:
                    return
                if action == "upload":
                    for path in base._character_dir(mod, slug).glob("*.*"):
                        if path.suffix.lower() in {".jpg", ".jpeg"}:
                            path.unlink(missing_ok=True)
                    context.user_data["ss205_admin_upload"] = {"slug": slug, "count": 0}
                    await q.message.reply_text(f"📥 Пришлите 3 JPEG для «{meta['name']}» по одному сообщению.")
                elif action == "clear":
                    for path in base._character_dir(mod, slug).glob("*.*"):
                        if path.suffix.lower() in {".jpg", ".jpeg"}:
                            path.unlink(missing_ok=True)
                    await q.message.reply_text(f"🗑 {meta['name']}: {base._character_status(mod, slug)}")
                else:
                    await q.message.reply_text(f"📊 {meta['name']}: {base._character_status(mod, slug)}")
                return
    finally:
        raise ApplicationHandlerStop


async def _mode_router(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop
    resolved = _mode(str(getattr(getattr(update, "effective_message", None), "text", "") or ""))
    if not resolved:
        return
    mod = _runtime(); user = getattr(update, "effective_user", None)
    if mod is None or user is None:
        return
    _clear(context, keep_photos=True)
    cleaner = getattr(mod, "_clear_transient_flows", None)
    if callable(cleaner):
        cleaner(context)
    key, name = resolved; setter = getattr(mod, "_set_mode_clean", None)
    if callable(setter):
        setter(int(user.id), name, "")
    sender = getattr(mod, "_send_mode_menu", None)
    if callable(sender):
        await sender(update, context, key)
    else:
        await update.effective_message.reply_text(f"✅ Режим «{name}» выбран.")
    raise ApplicationHandlerStop


def _install_builder() -> None:
    global _BUILDER
    if _BUILDER:
        return
    try:
        from telegram.ext import ApplicationBuilder, CallbackQueryHandler, MessageHandler, filters
    except Exception:
        return
    original = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original(self, *args, **kwargs)
        if not getattr(app, "_selfie_v208_bound", False):
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _mode_router), group=-1690)
            app.add_handler(CallbackQueryHandler(_admin_callback, pattern=r"^ss208:"), group=-1650)
            setattr(app, "_selfie_v208_bound", True)
        return app

    ApplicationBuilder.build = build
    _BUILDER = True


def patch() -> bool:
    from neyrobot_prod import celebrity_selfie as base
    from neyrobot_prod import celebrity_selfie_v204 as gen
    from neyrobot_prod import selfie_storage_v205 as storage
    from neyrobot_prod import selfie_runtime_v207 as runtime
    base.CHARACTERS.clear(); base.CHARACTERS.update(CHARACTERS); base.COUNTRIES = COUNTRIES
    base._user_photos = _photos; base._reset_user_photos = _reset_photos; base._append_user_photo = _append_photo
    base._clear_generation_state = lambda context, keep_active=True, keep_user_photos=True: _clear(context, keep_photos=keep_user_photos)
    base._finish_generation = lambda mod, context, user_id: _clear(context, keep_photos=True)
    base._country_kb = lambda mod: _country_kb(base, mod)
    base._character_kb = lambda mod, country=None: _character_kb(base, mod, country or "ru")
    base._main_kb = lambda mod: base._kb(mod, [[("📸 Загрузить 2 своих селфи", "cs201:photo")], [("✅ Последнее фото + добавить второе", "cs201:last")], [("⭐ Выбрать героя", "cs201:characters")], [("⬅️ Назад в Развлечения", "mode:fun")]])
    base.callback = _public_callback; base.media_entry = _public_media; base.text_entry = _public_text; base._generate = _generate
    storage.CHARACTER_ADDITIONS = {k: v for k, v in CHARACTERS.items() if k != "roman_abramovich"}
    storage._catalog_kb = lambda mod: _admin_catalog(storage, mod); storage.admin_command = _admin_command; storage.diagnostic = _diag_storage
    gen.VERSION = VERSION; gen.generate = _generate; gen.patch = lambda: (setattr(base, "_generate", _generate) or True)
    runtime.VERSION = VERSION; runtime.admin_command = _admin_command; runtime.diagnostic = _diag_storage
    mod = _runtime()
    if mod is not None:
        mod.CELEBRITY_SELFIE_VERSION = VERSION; mod.AI_SELFIE_RUNTIME_VERSION = VERSION; mod.CELEBRITY_SELFIE_ROUTE = "v208-comet-five-reference"; mod.SELFIE_STORAGE_VERSION = VERSION; mod.SELFIE_COMMANDS_VERSION = VERSION
    for slug in CHARACTERS:
        (Path("/data/celebrity_selfie") / "characters" / slug).mkdir(parents=True, exist_ok=True)
    return True


def install_async() -> None:
    global _STARTED
    _install_builder(); patch()
    if _STARTED:
        return
    _STARTED = True

    def worker() -> None:
        for _ in range(7200):
            with contextlib.suppress(Exception):
                patch()
            time.sleep(0.1)

    threading.Thread(target=worker, daemon=True, name="neyrobot-selfie-v208").start()


__all__ = ["VERSION", "COUNTRIES", "CHARACTERS", "install_async", "patch", "_mode", "_photos"]
