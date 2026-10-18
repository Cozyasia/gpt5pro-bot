"""Telegram adapter for the self-contained quiz. No provider calls or credit usage."""
from .games import start, current_question, answer, next_round, finish, GAME_BANKS
from . import adventures
from dataclasses import asdict
from .games import GameSession

def _keyboard():
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
    return M([[B("⚡ Быстрый квиз", callback_data="game:start:quick_quiz")],
              [B("🧠 Битва знаний", callback_data="game:start:knowledge")],
              [B("🎬 Угадай фильм", callback_data="game:start:movie")],
              [B("🕵️ Детектив", callback_data="game:adventure:detective")],
              [B("📖 Интерактивная история", callback_data="game:adventure:story")],
              [B("🐉 Ролевая игра", callback_data="game:adventure:roleplay")],
              [B("❤️ Игра для пары", callback_data="game:adventure:couple")],
              [B("🥳 Игра для компании", callback_data="game:adventure:party")],
              [B("🎲 Правда или действие", callback_data="game:adventure:truth_dare")],
              [B("⬅️ Развлечения", callback_data="ent:back:root")]])

def _round_keyboard(session):
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
    return M([[B(f"{key.upper()}. {value}", callback_data=f"game:answer:{session.round_index}:{key}")]
              for key, value in zip("abcd", current_question(session).answers)] +
             [[B("📜 Правила", callback_data="game:rules"), B("🛑 Закончить", callback_data="game:finish")]])

def _after_keyboard(session=None):
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
    return M([[B("➡️ Следующий раунд", callback_data=f"game:next:{session.round_index if session else 0}")],
              [B("🔄 Сыграть ещё", callback_data=f"game:start:{session.game_id if session else 'quick_quiz'}"),
               B("🛑 Закончить", callback_data="game:finish")]])

def _question_text(session):
    question = current_question(session)
    if question is None:
        return f"🏆 Игра завершена! Ваш результат: {session.score}."
    return (f"🎮 Раунд {session.round_index + 1}/{len(GAME_BANKS[session.game_id])}\n\n{question.prompt}\n\n" +
            "\n".join(f"{key.upper()}. {label}" for key, label in zip("abcd", question.answers)))

async def handle_game_menu(update, context):
    q = update.callback_query
    await q.answer()
    await q.message.reply_text("🎮 Игры с AI\nВыберите игру:", reply_markup=_keyboard())

async def handle_game_callback(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    raw_state = context.user_data.get("ent_game_session")
    state = GameSession(**raw_state) if isinstance(raw_state, dict) else raw_state
    if data.startswith("game:adventure:"):
        story_id = data.partition("game:adventure:")[2]
        try:
            adventure = adventures.start(story_id)
        except ValueError:
            await q.message.reply_text("Неизвестная история.", reply_markup=_keyboard())
            return
        context.user_data["ent_adventure"] = asdict(adventure)
        context.user_data.pop("ent_game_session", None)
        await _show_adventure(q.message, adventure)
        return
    if data.startswith("game:choose:"):
        raw_adventure = context.user_data.get("ent_adventure")
        adventure = adventures.Adventure(**raw_adventure) if isinstance(raw_adventure, dict) else raw_adventure
        if adventure is None:
            await q.message.reply_text("Сначала выберите историю.", reply_markup=_keyboard())
            return
        try:
            node_text, choice_text = data.partition("game:choose:")[2].split(":", 1)
            if int(node_text) != adventure.node:
                await q.message.reply_text("Этот выбор уже устарел. Продолжайте из последнего сообщения.")
                return
            adventure = adventures.choose(adventure, int(choice_text))
        except (ValueError, TypeError):
            await q.message.reply_text("Выберите доступный вариант.", reply_markup=_keyboard())
            return
        context.user_data["ent_adventure"] = asdict(adventure)
        await _show_adventure(q.message, adventure)
        return
    if data == "game:menu":
        context.user_data.pop("ent_adventure", None)
        await q.message.reply_text("🎮 Игры с AI\nВыберите игру:", reply_markup=_keyboard())
        return
    if data == "game:rules":
        await q.message.reply_text("📜 Выберите один ответ на вопрос. За верный ответ — 1 очко. Всего 5 раундов. Повторный ответ не засчитывается.",
                                   reply_markup=_keyboard() if state and state.finished else (_after_keyboard(state) if state and state.answered else (_round_keyboard(state) if state else _keyboard())))
        return
    if data.startswith("game:start:"):
        game_id = data.partition("game:start:")[2]
        if game_id not in GAME_BANKS:
            await q.message.reply_text("Неизвестная игра.", reply_markup=_keyboard())
            return
        state = start(game_id)
        context.user_data["ent_game_session"] = asdict(state)
        context.user_data.pop("ent_adventure", None)
        await q.message.reply_text(_question_text(state), reply_markup=_round_keyboard(state))
        return
    if data == "game:finish":
        context.user_data.pop("ent_adventure", None)
        if state:
            context.user_data["ent_game_session"] = asdict(finish(state))
        await q.message.reply_text(f"🏁 Игра окончена. Очки: {state.score if state else 0}.", reply_markup=_keyboard())
        return
    if state is None or state.finished:
        await q.message.reply_text("Сначала начните новую игру.", reply_markup=_keyboard())
        return
    if data.startswith("game:answer:"):
        payload = data[len("game:answer:"):]
        try:
            round_token, choice = payload.split(":", 1)
            if int(round_token) != state.round_index:
                await q.message.reply_text("Этот вопрос уже завершён. Продолжайте из последнего сообщения.")
                return
        except (ValueError, TypeError):
            await q.message.reply_text("Кнопка устарела. Откройте игру заново.", reply_markup=_keyboard())
            return
        if state.answered:
            await q.message.reply_text("Ответ уже принят. Нажмите «Следующий раунд».", reply_markup=_after_keyboard(state))
            return
        try:
            updated, correct = answer(state, choice)
        except ValueError:
            await q.message.reply_text("Неверная кнопка. Выберите один из четырёх ответов.", reply_markup=_round_keyboard(state))
            return
        context.user_data["ent_game_session"] = asdict(updated)
        question = current_question(state)
        await q.message.reply_text(("✅ Верно!" if correct else f"❌ Неверно. Правильный ответ: {question.correct.upper()}.") +
                                   f"\n{question.explanation}\nОчки: {updated.score}",
                                   reply_markup=_after_keyboard(updated))
        return
    if data.startswith("game:next:"):
        try:
            if int(data.partition("game:next:")[2]) != state.round_index:
                await q.message.reply_text("Раунд уже изменился. Используйте актуальные кнопки.")
                return
        except (ValueError, TypeError):
            await q.message.reply_text("Некорректная кнопка.", reply_markup=_keyboard())
            return
        if not state.answered:
            await q.message.reply_text("Сначала ответьте на вопрос.", reply_markup=_round_keyboard(state))
            return
        updated = next_round(state)
        context.user_data["ent_game_session"] = asdict(updated)
        if updated.finished:
            await q.message.reply_text(f"🏆 Игра завершена! Ваш результат: {updated.score}/{len(GAME_BANKS[updated.game_id])}.", reply_markup=_keyboard())
        else:
            await q.message.reply_text(_question_text(updated), reply_markup=_round_keyboard(updated))
        return
    await q.message.reply_text("Выберите игру:", reply_markup=_keyboard())

async def _show_adventure(message, session):
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
    prompt, options, _ = adventures.scene(session)
    rows = [[B(label, callback_data=f"game:choose:{session.node}:{i}")] for i, label in enumerate(options)]
    rows.append([B("🔄 Другая история", callback_data="game:menu")])
    await message.reply_text(prompt, reply_markup=M(rows))
