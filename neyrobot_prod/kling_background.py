"""Run one image-to-video job per user without blocking Telegram's queue."""
import logging

log = logging.getLogger(__name__)

class _ContextSnapshot:
    def __init__(self, original):
        self._original = original
        self.user_data = dict(original.user_data)
    def __getattr__(self, name):
        return getattr(self._original, name)

async def _schedule(update, context, action):
    running = context.application.bot_data.setdefault('_kling_background_running', set())
    user_id = int(update.effective_user.id)
    if user_id in running:
        query = getattr(update, 'callback_query', None)
        if query and callable(getattr(query, 'answer', None)):
            await query.answer('Генерация уже выполняется.', show_alert=True)
        else:
            await update.effective_message.reply_text('Генерация Kling уже выполняется. Дождитесь результата.')
        return False
    running.add(user_id)
    async def worker():
        try:
            await action()
        except Exception:
            log.exception('Background Kling operation failed')
            await update.effective_message.reply_text('Не удалось завершить задачу. Проверьте её статус перед повторным запуском.')
        finally:
            running.discard(user_id)
    coro = worker()
    try:
        context.application.create_task(coro, update=update, name='kling-image-to-video')
    except BaseException:
        coro.close()
        running.discard(user_id)
        raise
    return True

async def schedule_i2v(update, context, prompt, generate, photo_lookup):
    snapshot = _ContextSnapshot(context)
    photo = photo_lookup(update.effective_user.id) or b""
    return await _schedule(update, context, lambda: generate(update, snapshot, prompt, reference_bytes=photo))

async def schedule_confirmation(update, context, confirm):
    return await _schedule(update, context, lambda: confirm(update, context))
