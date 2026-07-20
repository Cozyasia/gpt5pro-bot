# -*- coding: utf-8 -*-
"""v138: Neyro-Bot white/blue UI profile and soft Celebrity Selfie delivery.

Telegram controls the actual palette.  Native buttons support only the default
neutral style plus predefined primary/success/danger backgrounds, so this layer
uses neutral (white/transparent according to the Telegram theme) buttons and a
single blue primary action instead of painting the whole keyboard blue/green.

Celebrity Selfie keeps structural hard gates (valid image, one continuous frame,
at least two usable faces, no obvious reference sheet/split screen), but identity
scores become ranking/verification signals.  A structurally valid best candidate
may be delivered as a clearly labelled preview instead of being silently hidden.
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
import uuid
from io import BytesIO
from typing import Any

import celebrity_selfie_v136 as selfie
import chat_provider_v136 as chats
import ui_hotfix_v137 as ui137

VERSION = "v138-brand-palette-selfie-preview-2026-07-20"
_GROUP = -80000
_BUILDER_FLAG = "_ui_selfie_v138_builder"
_HANDLER_FLAG = "_ui_selfie_v138_handlers"
log = logging.getLogger("gpt-bot.ui-selfie-v138")

_ORIGINAL_SCENE_ASSESSMENT = selfie.v134._scene_assessment
_ORIGINAL_IDENTITY_QC = selfie._identity_detail_qc


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().casefold() not in {"0", "false", "no", "off", ""}


def _number(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float((os.environ.get(name) or str(default)).replace(",", "."))
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _custom_emoji_id(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    return value if value.isdigit() else ""


def _api_kwargs(*, primary: bool = False, icon_env: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if primary:
        result["style"] = "primary"
    if icon_env:
        icon_id = _custom_emoji_id(icon_env)
        if icon_id:
            result["icon_custom_emoji_id"] = icon_id
    return result


def _label(text: str, fallback_icon: str, icon_env: str) -> str:
    return text if _custom_emoji_id(icon_env) else f"{fallback_icon} {text}"


def _inline_button(
    text: str,
    callback_data: str,
    *,
    primary: bool = False,
    icon_env: str | None = None,
):
    from telegram import InlineKeyboardButton

    kwargs = _api_kwargs(primary=primary, icon_env=icon_env)
    return InlineKeyboardButton(text=text, callback_data=callback_data, api_kwargs=kwargs or None)


def _photo_choice_kb(has_cached: bool):
    """Neutral white/default buttons; upload remains Telegram's paperclip/camera."""
    from telegram import InlineKeyboardMarkup

    rows = []
    if has_cached:
        rows.append([
            _inline_button(
                "Использовать последнее фото",
                "cs126:use_last",
                primary=True,
                icon_env="SELFIE_LAST_PHOTO_CUSTOM_EMOJI_ID",
            )
        ])
    rows.append([
        _inline_button("Отмена", "cs126:cancel", icon_env="CANCEL_CUSTOM_EMOJI_ID")
    ])
    return InlineKeyboardMarkup(rows)


def _second_angle_kb():
    from telegram import InlineKeyboardMarkup

    return InlineKeyboardMarkup([
        [
            _inline_button(
                "Добавить второй ракурс",
                "cs136:add_user_ref",
                icon_env="SELFIE_SECOND_ANGLE_CUSTOM_EMOJI_ID",
            )
        ],
        [
            _inline_button(
                "Продолжить с одним фото",
                "cs136:continue_one",
                primary=True,
                icon_env="CONTINUE_CUSTOM_EMOJI_ID",
            )
        ],
        [
            _inline_button("Отмена", "cs126:cancel", icon_env="CANCEL_CUSTOM_EMOJI_ID")
        ],
    ])


def _chat_provider_markup(provider: str):
    from telegram import InlineKeyboardMarkup

    provider = chats._normal_provider(provider)
    gpt_text = _label("Чат с GPT", "◉", "GPT_BUTTON_CUSTOM_EMOJI_ID")
    gemini_text = _label("Чат с Gemini", "✦", "GEMINI_BUTTON_CUSTOM_EMOJI_ID")
    if provider == "gpt":
        gpt_text = "✓ " + gpt_text
    else:
        gemini_text = "✓ " + gemini_text
    return InlineKeyboardMarkup([
        [
            _inline_button(
                gpt_text,
                "chatprov:gpt",
                primary=provider == "gpt",
                icon_env="GPT_BUTTON_CUSTOM_EMOJI_ID",
            )
        ],
        [
            _inline_button(
                gemini_text,
                "chatprov:gemini",
                primary=provider == "gemini",
                icon_env="GEMINI_BUTTON_CUSTOM_EMOJI_ID",
            )
        ],
        [
            _inline_button(
                "Очистить историю выбранного чата",
                "chatprov:clear",
                icon_env="CLEAR_HISTORY_CUSTOM_EMOJI_ID",
            )
        ],
    ])


def _reply_icon_env(text: str) -> str:
    low = text.casefold()
    if "новый чат" in low:
        return "NEW_CHAT_CUSTOM_EMOJI_ID"
    if "мои чаты" in low:
        return "CHATS_CUSTOM_EMOJI_ID"
    if "gpt" in low:
        return "GPT_BUTTON_CUSTOM_EMOJI_ID"
    if "gemini" in low:
        return "GEMINI_BUTTON_CUSTOM_EMOJI_ID"
    return ""


def _neutral_reply_button(button: Any):
    from telegram import KeyboardButton

    text = str(getattr(button, "text", button) or "")
    special = any(
        getattr(button, name, None) is not None
        for name in (
            "request_users", "request_chat", "request_contact", "request_location",
            "request_poll", "web_app",
        )
    )
    if special:
        return button
    kwargs = _api_kwargs(icon_env=_reply_icon_env(text))
    return KeyboardButton(text=text, api_kwargs=kwargs or None)


def patch_main_keyboard(mod: Any) -> None:
    """Restore a calm neutral keyboard instead of the v137 all-colour palette."""
    try:
        from telegram import ReplyKeyboardMarkup

        markup = getattr(mod, "main_kb", None)
        keyboard = getattr(markup, "keyboard", None)
        if not keyboard:
            return
        rows = [[_neutral_reply_button(button) for button in row] for row in keyboard]
        mod.main_kb = ReplyKeyboardMarkup(
            rows,
            resize_keyboard=bool(getattr(markup, "resize_keyboard", True)),
            one_time_keyboard=bool(getattr(markup, "one_time_keyboard", False)),
            selective=bool(getattr(markup, "selective", False)),
            input_field_placeholder=getattr(markup, "input_field_placeholder", None),
            is_persistent=getattr(markup, "is_persistent", None),
        )
    except Exception as exc:
        log.warning("Cannot apply v138 neutral main keyboard: %s", exc)


async def _scene_assessment_soft(mod: Any, raw: bytes, scene: str, *, phase: str) -> dict[str, Any]:
    """Keep real structural failures hard; do not reject a good pair for bystanders."""
    result = await _ORIGINAL_SCENE_ASSESSMENT(mod, raw, scene, phase=phase)
    if result.get("hard_ok"):
        return result
    reason = str(result.get("reason") or "")
    local = float(result.get("local_score") or 0)
    if local > 0 and reason.startswith("foreground_people="):
        with contextlib.suppress(Exception):
            people = int(reason.split("=", 1)[1])
            if people > 2:
                result.update({
                    "hard_ok": True,
                    "reason": f"soft-background-bystanders:{people}",
                    "total_score": float(result.get("total_score") or local),
                })
    return result


async def _identity_detail_qc_soft(
    mod: Any,
    output: bytes,
    user_photo: bytes,
    celebrity_ref: bytes,
) -> dict[str, Any]:
    result = await _ORIGINAL_IDENTITY_QC(mod, output, user_photo, celebrity_ref)
    minimum = float(result.get("minimum") or 0)
    if minimum > 0:
        result["identity_unknown"] = False
        return result

    reason = str(result.get("reason") or "").casefold()
    hard_words = (
        "split", "collage", "reference", "повреж", "одно уверенное лицо",
        "only one", "identities blended", "merged identity", "одинаков",
    )
    if any(word in reason for word in hard_words):
        result["identity_unknown"] = False
        return result

    problem = selfie.base._image_problem(output, stage="preview", require_two_faces=True)
    if problem:
        result["reason"] = problem
        result["identity_unknown"] = False
        return result

    floor = _number("CELEBRITY_V138_PREVIEW_IDENTITY_FLOOR", 32.0, 20.0, 50.0)
    result.update({
        "user": floor,
        "celebrity": floor,
        "minimum": floor,
        "weighted": floor,
        "identity_unknown": True,
        "reason": f"preview-qc-soft:{result.get('reason') or 'identity score unavailable'}"[:300],
    })
    return result


async def _score_candidate_soft(
    mod: Any,
    raw: bytes,
    user: bytes,
    ref: bytes,
    scene: str,
    label: str,
) -> dict[str, Any]:
    assessment = await _scene_assessment_soft(mod, raw, scene, phase=label)
    if not assessment.get("hard_ok"):
        raise RuntimeError(str(assessment.get("reason") or "broken composition"))
    identity = await _identity_detail_qc_soft(mod, raw, user, ref)
    minimum = float(identity.get("minimum") or 0)
    if minimum <= 0:
        raise RuntimeError(str(identity.get("reason") or "identity failed"))
    composition = float(
        assessment.get("total_score")
        or assessment.get("composition_score")
        or assessment.get("local_score")
        or 0
    )
    scene_score = float(assessment.get("scene_score") or 0)
    weighted = float(identity.get("weighted") or minimum)
    total = minimum * 0.52 + weighted * 0.31 + composition * 0.12 + scene_score * 0.05
    return {
        "total": round(total, 1),
        "user_identity": round(float(identity.get("user") or minimum), 1),
        "celebrity_identity": round(float(identity.get("celebrity") or minimum), 1),
        "identity_min": round(minimum, 1),
        "identity_weighted": round(weighted, 1),
        "identity_unknown": bool(identity.get("identity_unknown")),
        "composition": round(composition, 1),
        "scene": round(scene_score, 1),
        "label": label,
        "reason": identity.get("reason"),
        "output": raw,
    }


def _delivery_state(selected: dict[str, Any]) -> tuple[str, float]:
    identity = float(selected.get("identity_min") or 0)
    verified = _number("CELEBRITY_V138_VERIFIED_IDENTITY", 58.0, 40.0, 90.0)
    if selected.get("identity_unknown") or identity < verified:
        return "preview", identity
    return "verified", identity


async def _generate(update: Any, context: Any, *, refinement: bool = False) -> None:
    engine = selfie.engine
    session = engine._session(context, create=False)
    if not session:
        await update.effective_message.reply_text("Сессия AI-селфи не найдена. Откройте режим заново.")
        return
    now = time.monotonic()
    if str(session.get("state") or "") in {"queued", "generating"} and now - float(session.get("generation_started_monotonic") or 0) < 1500:
        await update.effective_message.reply_text("⏳ Эта генерация уже выполняется. Дождитесь результата.")
        return

    user_photo = engine._read_path(session.get("user_photo_path"))
    second_user = engine._read_path(session.get("user_photo_2_path"))
    refs = [raw for raw in (engine._read_path(path) for path in engine._reference_paths(session)) if raw]
    scene = str(session.get("scene") or "").strip()
    celebrity_name = str(
        session.get("celebrity_name")
        or session.get("selected_celebrity_name")
        or "выбранный человек"
    ).strip()
    if not user_photo:
        session["state"] = "await_user_photo"
        await update.effective_message.reply_text("Пришлите своё чёткое селфи ещё раз.")
        return
    if not refs:
        session["state"] = "await_custom_refs"
        await update.effective_message.reply_text("Загрузите 1–4 чётких фото выбранной персоны.")
        return
    if not scene:
        session["state"] = "await_scene"
        await update.effective_message.reply_text("Выберите или опишите сцену.", reply_markup=engine._scene_kb())
        return

    mod = engine._runtime_module()
    if mod is None:
        await update.effective_message.reply_text("Сервис ещё загружается. Повторите через несколько секунд.")
        return
    previous_result = engine._read_path(session.get("result_path")) if refinement else None
    generation_id = uuid.uuid4().hex
    session.update({
        "generation_id": generation_id,
        "generation_started_monotonic": now,
        "generation_scene_snapshot": scene,
        "generation_celebrity_snapshot": celebrity_name,
        "state": "queued",
    })

    async def work() -> bool:
        if not selfie.base_guard._same_job_selection(session, generation_id, scene, celebrity_name):
            return False
        session["state"] = "generating"
        await update.effective_message.reply_text(
            "⏳ Точечно улучшаю слабое лицо, не меняя удачный кадр…" if refinement else
            f"⏳ Создаю несколько цельных селфи с {celebrity_name}, проверяю композицию и сходство. "
            "Если сходство окажется ниже целевого, покажу лучший безопасный кадр как предварительный результат."
        )
        try:
            output = await selfie._run_v136_generation(
                mod,
                user_photo,
                refs,
                celebrity_name,
                scene,
                previous_result=previous_result,
                additional_user_refs=[second_user] if second_user else [],
            )
        except Exception as exc:
            if str(session.get("generation_id") or "") == generation_id:
                session["state"] = "result" if previous_result else "await_scene"
                session["last_generation_error"] = str(exc)[:2200]
                session["last_generation_failed_at"] = time.time()
                session["generation_failures"] = int(session.get("generation_failures") or 0) + 1
                session.pop("generation_id", None)
                await update.effective_message.reply_text(
                    "❌ Не удалось получить даже структурно корректный кадр: изображение было повреждено, "
                    "содержало склейку либо не имело двух пригодных лиц. Можно повторить сцену или выбрать другую.",
                    reply_markup=selfie.v133._failure_kb(),
                )
            return False

        if not selfie.base_guard._same_job_selection(session, generation_id, scene, celebrity_name):
            if str(session.get("generation_id") or "") == generation_id:
                session.pop("generation_id", None)
            return False

        selected = (selfie._LAST_RUN_DEBUG or {}).get("selected") or {}
        delivery_mode, identity_min = _delivery_state(selected)
        session["delivery_mode"] = delivery_mode
        session["delivery_identity_min"] = identity_min
        session["result_path"] = engine._store_image(
            session,
            "result_refined.jpg" if refinement else "result.jpg",
            output,
        )
        session["state"] = "result"
        session["last_generation_ok_at"] = time.time()
        session["generation_failures"] = 0
        session.pop("generation_id", None)

        from telegram import InputFile

        bio = BytesIO(output)
        bio.name = "celebrity_selfie.jpg"
        if delivery_mode == "verified":
            quality_line = (
                f"Качество: проверенный результат; минимальная оценка сходства {identity_min:.0f}/100."
            )
            title = "📸 AI-селфи готово ✅"
        else:
            quality_line = (
                "Качество: предварительный результат — композиция прошла обязательные проверки, "
                f"но сходство одного лица ниже целевого уровня ({identity_min:.0f}/100). "
                "Кадр показан для визуальной оценки; его можно улучшить или повторить."
            )
            title = "📸 Предварительный AI-результат"
        caption = (
            f"{title}\n"
            f"Персона: {celebrity_name}\n"
            f"Формат: {selfie._aspect_for_scene(scene)}, {selfie._image_size()}.\n"
            f"{quality_line}\n"
            "Пометка: изображение создано ИИ; оно не подтверждает реальную встречу, поддержку, рекламу или партнёрство."
        )
        markup = engine._result_kb(bool(engine._selected_entry(session)))
        if engine._flag("CELEBRITY_SELFIE_SEND_AS_DOCUMENT", True):
            await update.effective_message.reply_document(InputFile(bio), caption=caption[:1024], reply_markup=markup)
        else:
            await update.effective_message.reply_photo(photo=output, caption=caption[:1024], reply_markup=markup)
        return True

    pay = getattr(mod, "_try_pay_then_do", None)
    if not callable(pay):
        await work()
        return
    cost = float(os.environ.get("CELEBRITY_V136_UNIT_COST_USD") or 0.60)
    await pay(
        update,
        context,
        update.effective_user.id,
        "img",
        cost,
        work,
        remember_kind="celebrity_selfie_v138_refine" if refinement else "celebrity_selfie_v138",
        remember_payload={
            "celebrity": celebrity_name,
            "scene": scene[:500],
            "refinement": refinement,
            "generation_id": generation_id,
            "pipeline": VERSION,
            "aspect": selfie._aspect_for_scene(scene),
            "user_references": 2 if second_user else 1,
            "soft_delivery": True,
        },
    )


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    session = selfie.engine._session(context, create=False)
    debug = selfie._LAST_RUN_DEBUG or {}
    selected = debug.get("selected") or {}
    mode, identity = _delivery_state(selected) if selected else ("-", 0.0)
    await update.effective_message.reply_text(
        f"📸 Celebrity Selfie / {VERSION}\n"
        "palette=telegram-neutral-white+primary-blue\n"
        "custom_hex_or_border=not_supported_by_native_buttons\n"
        "hard_gates=valid_file+single_frame+two_usable_faces+no_reference_sheet\n"
        "identity_gate=soft_rank_and_preview\n"
        f"preview_floor={_number('CELEBRITY_V138_PREVIEW_IDENTITY_FLOOR', 32, 20, 50):.0f}\n"
        f"verified_threshold={_number('CELEBRITY_V138_VERIFIED_IDENTITY', 58, 40, 90):.0f}\n"
        f"delivery_mode={session.get('delivery_mode', mode) if session else mode}\n"
        f"identity_min={session.get('delivery_identity_min', identity) if session else identity}\n"
        f"candidate_count={len(debug.get('candidates') or [])}\n"
        f"repair_count={len(debug.get('repairs') or [])}\n"
        f"selected={str(selected or '-')[:1000]}\n"
        f"errors={' | '.join(str(item) for item in (debug.get('errors') or [])[-5:])[:1300] or '-'}\n"
        f"last_error={(session.get('last_generation_error') or '-')[:900] if session else '-'}"
    )
    raise ApplicationHandlerStop


def install_runtime_patches() -> None:
    os.environ.setdefault("CELEBRITY_V136_MIN_DELIVERY_IDENTITY", "28")
    os.environ.setdefault("CELEBRITY_V138_PREVIEW_IDENTITY_FLOOR", "32")
    os.environ.setdefault("CELEBRITY_V138_VERIFIED_IDENTITY", "58")

    # UI profile.
    selfie.wizard._photo_choice_kb = _photo_choice_kb
    selfie._second_angle_kb = _second_angle_kb
    chats._provider_markup = _chat_provider_markup
    ui137._photo_choice_kb = _photo_choice_kb
    ui137._second_angle_kb = _second_angle_kb
    ui137._chat_provider_markup = _chat_provider_markup
    ui137.patch_main_keyboard = patch_main_keyboard

    current_patch = getattr(chats, "_patch_main_keyboard", None)
    if callable(current_patch) and not getattr(current_patch, "_ui_selfie_v138", False):
        def patched(mod: Any) -> None:
            current_patch(mod)
            patch_main_keyboard(mod)

        setattr(patched, "_ui_selfie_v138", True)
        chats._patch_main_keyboard = patched

    # Selfie quality policy.
    selfie.v134._scene_assessment = _scene_assessment_soft
    selfie._identity_detail_qc = _identity_detail_qc_soft
    selfie._score_candidate = _score_candidate_soft
    selfie._generate = _generate
    selfie.engine._generate = _generate
    selfie.v133._generate = _generate
    selfie.engine._diag = _diag


def install_async() -> None:
    def worker() -> None:
        stable = 0
        for _ in range(1200):
            mod = chats._runtime_module()
            if mod is None or not getattr(mod, "main_kb", None):
                time.sleep(0.1)
                continue
            try:
                patch_main_keyboard(mod)
                stable += 1
                if stable >= 30:
                    return
            except Exception:
                stable = 0
            time.sleep(0.15)

    threading.Thread(target=worker, name="ui-selfie-v138", daemon=True).start()


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, _HANDLER_FLAG, False):
            app.add_handler(CommandHandler("diag_celebrity_flow", _diag), group=_GROUP)
            app.add_handler(CommandHandler("diag_brand", _diag), group=_GROUP)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


install_runtime_patches()

__all__ = [
    "VERSION", "install_runtime_patches", "install_async", "install_builder_hook",
    "patch_main_keyboard", "_photo_choice_kb", "_second_angle_kb",
    "_chat_provider_markup", "_scene_assessment_soft", "_identity_detail_qc_soft",
    "_score_candidate_soft", "_delivery_state", "_generate", "_diag",
]
