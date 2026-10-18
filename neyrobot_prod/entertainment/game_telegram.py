"""Telegram adapter for the self-contained quiz. No provider calls or credit usage."""
from .games import start, current_question, answer, next_round, finish

def _keyboard():
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
    return M([[B("⚡ Быстрый квиз", callback_data="game:start")],
              [B("⬅️ Развлечения", callback_data="ent:back:root")]])

def _round_keyboard(session):
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
    return M([[B(f"{key.upper()}. {value}", callback_data=f"game:answer:{key}")]
              for key, value in zip("abcd", current_question(session).answers)] +
             [[B("📜 Правила", callback_data="game:rules"), B("🛑 Закончить", callback_data="game:finish")]])

def _after_keyboard():
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
    return M([[B("➡️ Следующий раунд", callback_data="game:next")],
              [B("🔄 Сыграть ещё", callback_data="game:start"),
               B("🛑 Закончить", callback_data="game:finish")]])

def _question_text(session):
    question = current_question(session)
    if question is None:
        return f"🏆 Игра завершена! Ваш результат: {session.score}."
    return (f"🎮 Раунд {session.round_index + 1}/5\n\n{question.prompt}\n\n" +
            "\n".join(f"{key.upper()}. {label}" for key, label in zip("abcd", question.answers)))

async def handle_game_callback(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    state = context.user_data.get("ent_game_session")
    if data == "game:menu":
        await q.message.reply_text("🎮 Игры с AI\nВыберите игру:", reply_markup=_keyboard())
        return
    if data == "game:rules":
        await q.message.reply_text("📜 Выберите один ответ на вопрос. За верный ответ — 1 очко. Всего 5 раундов. Повторный ответ не засчитывается.",
                                   reply_markup=_after_keyboard() if state and state.answered else _keyboard())
        return
    if data == "game:start":
        state = start()
        context.user_data["ent_game_session"] = state
        await q.message.reply_text(_question_text(state), reply_markup=_round_keyboard(state))
        return
    if data == "game:finish":
        if state:
            context.user_data["ent_game_session"] = finish(state)
        await q.message.reply_text(f"🏁 Игра окончена. Очки: {state.score if state else 0}.", reply_markup=_keyboard())
        return
    if state is None or state.finished:
        await q.message.reply_text("Сначала начните новую игру.", reply_markup=_keyboard())
        return
    if data.startswith("game:answer:"):
        choice = data[len("game:answer:"):]
        if state.answered:
            await q.message.reply_text("Ответ уже принят. Нажмите «Следующий раунд».", reply_markup=_after_keyboard())
            return
        try:
            updated, correct = answer(state, choice)
        except ValueError:
            await q.message.reply_text("Неверная кнопка. Выберите один из четырёх ответов.", reply_markup=_round_keyboard(state))
            return
        context.user_data["ent_game_session"] = updated
        question = current_question(state)
        await q.message.reply_text(("✅ Верно!" if correct else f"❌ Неверно. Правильный ответ: {question.correct.upper()}.") +
                                   f"\n{question.explanation}\nОчки: {updated.score}",
                                   reply_markup=_after_keyboard())
        return
    if data == "game:next":
        if not state.answered:
            await q.message.reply_text("Сначала ответьте на вопрос.", reply_markup=_round_keyboard())
            return
        updated = next_round(state)
        context.user_data["ent_game_session"] = updated
        if updated.finished:
            await q.message.reply_text(f"🏆 Игра завершена! Ваш результат: {updated.score}/5.", reply_markup=_keyboard())
        else:
            await q.message.reply_text(_question_text(updated), reply_markup=_round_keyboard())
        return
    await q.message.reply_text("Выберите игру:", reply_markup=_keyboard())
