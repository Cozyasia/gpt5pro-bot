"""Telegram entry points for quoted, single-segment translated lip sync.

Prices are explicitly configured; the adapter never invents provider rates.
A quote lives only in memory, so restarting before confirmation expires it.
An operation identifier derived from the incoming message is persisted by the
ledger before any provider call, including after a Telegram update is replayed.
"""
import asyncio
import math
import os
import secrets
import time

from .translation_paid_service import make_quote
from .translation_public_flow import run_short_translation

LANGUAGES = {'ru': ('Русский', 'Russian'), 'en': ('Английский', 'English'),
             'th': ('Тайский', 'Thai'), 'es': ('Испанский', 'Spanish')}
PRICE_KEYS = {'identify_per_segment': 'TRANSLATION_IDENTIFY_USD',
              'lipsync_per_segment': 'TRANSLATION_LIPSYNC_USD',
              'transcription': 'TRANSLATION_STT_USD',
              'translation': 'TRANSLATION_TEXT_USD',
              'speech': 'TRANSLATION_TTS_USD'}


def _keyboard(g, rows):
    return g['InlineKeyboardMarkup']([[g['InlineKeyboardButton'](label, callback_data=data)
                                       for label, data in row] for row in rows])


def _rates():
    # Explicitly configured totals are estimates for the maximum supported clip.
    return {key: os.environ.get(name) for key, name in PRICE_KEYS.items()}


async def open_menu(update, context, g):
    q = update.callback_query
    await q.answer()
    g['_clear_transient_flows'](context)
    g['_set_mode_clean'](q.from_user.id, 'Нейро Продакшен', 'video_translation')
    context.user_data['video_translation_lipsync_public'] = True
    context.user_data['translation_choose_language'] = True
    await q.message.reply_text('🌍 Выберите язык перевода и новой озвучки:', reply_markup=_keyboard(g, [
        [('🇷🇺 Русский', 'vtr:lang:ru'), ('🇬🇧 Английский', 'vtr:lang:en')],
        [('🇹🇭 Тайский', 'vtr:lang:th'), ('🇪🇸 Испанский', 'vtr:lang:es')]]))


async def prepare(update, context, video, g):
    lang = context.user_data.get('video_translation_language')
    if lang not in LANGUAGES:
        await update.effective_message.reply_text('Сначала выберите язык в разделе «Перевод видео».')
        return
    duration = await asyncio.to_thread(g['_generated_video_duration_seconds_sync'], video)
    if not math.isfinite(duration) or not 2 <= duration <= 10:
        await update.effective_message.reply_text('Нужен MP4 с речью длительностью от 2 до 10 секунд и размером до 50 МБ.')
        return
    if not (g['OPENAI_STT_KEY'] and g['OPENAI_TTS_KEY'] and g['KLING_LIPSYNC_ENABLED'] and
            (g['KLING_API_KEY'] or g['COMET_API_KEY'])):
        await update.effective_message.reply_text('⚠️ Перевод с синхронизацией сейчас недоступен. Попробуйте позже.')
        return
    try:
        quote = make_quote(duration, pricing=_rates(), retail_quote=lambda cost: (g['_retail_usd'](cost), g['_retail_credits'](cost)))
    except (TypeError, ValueError, OverflowError):
        await update.effective_message.reply_text('⚠️ Стоимость пока недоступна. Генерация не запущена.')
        return
    user = update.effective_user
    unlimited = bool(g['is_unlimited'](user.id, user.username or ''))
    if not unlimited and g['_wallet_available_get'](user.id) + 1e-9 < quote.retail_cost:
        await update.effective_message.reply_text(f'Недостаточно кредитов. Стоимость: {quote.credits:g} кр. Пополните баланс и загрузите видео заново.')
        return
    pending = context.application.bot_data.setdefault('_translation_quotes', {})
    now = time.time()
    for token, item in list(pending.items()):
        if item['expires'] < now or item['user_id'] == user.id:
            pending.pop(token, None)
    if len(pending) >= 5:
        await update.effective_message.reply_text('⚠️ Сервис занят. Попробуйте загрузить видео немного позже.')
        return
    token = secrets.token_hex(16)
    pending[token] = {'user_id': user.id, 'chat_id': update.effective_chat.id,
                      'request_id': f'translation:{update.effective_chat.id}:{update.effective_message.message_id}',
                      'video': video, 'duration': duration, 'language': lang, 'quote': quote,
                      'unlimited': unlimited, 'expires': now + 900, 'update': update}
    asyncio.get_running_loop().call_later(900, pending.pop, token, None)
    price = '0 кр. по вашему безлимиту' if unlimited else f'{quote.credits:g} кр.'
    await update.effective_message.reply_text(
        f'🎬 Видео: {duration:.1f} сек. Язык: {LANGUAGES[lang][0]}.\n'
        f'Перевод, новая озвучка и Kling Lip Sync. Стоимость: {price}.\n'
        'Подтвердите запуск. Списание — после подтверждённой отправки результата. '
        'Предложение действует 15 минут.',
        reply_markup=_keyboard(g, [[('✅ Запустить', 'vtr:yes:' + token), ('Отмена', 'vtr:no:' + token)]]))


async def callback(update, context, g):
    q = update.callback_query
    parts = (q.data or '').split(':')
    if len(parts) != 3:
        await q.answer('Некорректная команда', show_alert=True); return
    if parts[1] == 'lang':
        if not context.user_data.get('translation_choose_language') or parts[2] not in LANGUAGES:
            await q.answer('Выбор устарел. Откройте перевод заново.', show_alert=True); return
        context.user_data.pop('translation_choose_language', None)
        context.user_data['video_translation_language'] = parts[2]
        context.user_data['awaiting_video_translation_upload'] = True
        await q.answer()
        await q.message.reply_text(f'Язык: {LANGUAGES[parts[2]][0]}. Пришлите MP4 с речью: 2–10 секунд, до 50 МБ. После загрузки покажу стоимость.')
        return
    if parts[1] not in ('yes', 'no'):
        await q.answer('Некорректная команда', show_alert=True); return
    pending = context.application.bot_data.setdefault('_translation_quotes', {})
    item = pending.get(parts[2])
    if not item or item['user_id'] != q.from_user.id or item['chat_id'] != update.effective_chat.id:
        await q.answer('Предложение недоступно или истекло.', show_alert=True); return
    pending.pop(parts[2], None)
    if item['expires'] < time.time():
        await q.answer('Предложение истекло. Загрузите видео заново.', show_alert=True); return
    if parts[1] == 'no':
        await q.answer(); await q.message.reply_text('Отменено. Кредиты не списаны.'); return
    current_unlimited = bool(g['is_unlimited'](q.from_user.id, q.from_user.username or ''))
    if current_unlimited != item['unlimited']:
        await q.answer('Условия аккаунта изменились. Загрузите видео заново.', show_alert=True); return
    await q.answer()
    await q.message.reply_text('🌍 Принято. Перевожу речь, создаю озвучку и синхронизирую губы. Это может занять несколько минут.')

    async def dub(video, duration, language):
        source_audio = await asyncio.to_thread(g['_extract_video_audio_sync'], video)
        transcript = await g['_stt_transcribe_bytes']('source.mp3', source_audio)
        if not transcript: raise RuntimeError('empty transcript')
        translated = await g['ask_openai_text'](
            f'Translate this spoken-video transcript into {language}. Preserve meaning, names, tone and paragraph breaks. Return only the translated narration, with no notes:\n\n' + transcript)
        if not translated or translated.startswith('⚠️ Сейчас не получилось получить ответ от модели.'):
            raise RuntimeError('translation model did not return a translation')
        parts = g['_split_tts_text'](translated, g['TTS_MAX_CHARS'])
        speech = [await asyncio.to_thread(g['_tts_bytes_sync'], part, 'mp3', g['_avatar_tts_voice_get'](context)) for part in parts]
        if not speech or any(not v for v in speech): raise RuntimeError('empty speech')
        audio = await asyncio.to_thread(g['_concat_audio_mp3_sync'], speech)
        return await asyncio.to_thread(g['_mux_translated_audio_sync'], video, audio, duration)

    async def kling(video_url, audio_url, *, duration_ms, on_provider_state):
        return await g['_run_kling_lipsync_result_bytes'](video_url, audio_url, duration_ms=duration_ms, on_provider_state=on_provider_state, retry_identify_unknown=False)

    async def deliver(video):
        return await g['_reply_video_bytes'](item['update'], video,
            f'✅ Перевод, озвучка и синхронизация готовы · {LANGUAGES[item["language"]][0]}.', task_id=item['request_id'])

    try:
        result = await run_short_translation(db_path=g['DB_PATH'], request_id=item['request_id'],
            user_id=item['user_id'], source_video=item['video'], duration=item['duration'],
            language=LANGUAGES[item['language']][1], quote=item['quote'], transcribe_and_dub=dub,
            publish=g['_provider_input_url_from_bytes'], kling=kling, deliver=deliver,
            charge_user=not item['unlimited'])
        messages = {'delivered': '✅ Готово. ' + ('Доступ по безлимиту, кредиты не списаны.' if item['unlimited'] else f'Списано {item["quote"].credits:g} кр.'),
                    'already_started': 'Этот запрос уже запущен или обработан. Повторно не запускаю и не списываю.',
                    'unknown': '⚠️ Статус результата уточняется. Повторно не запускайте запрос; обратитесь в поддержку.',
                    'failed': 'Не удалось выполнить запрос. Кредиты не списаны.'}
        await q.message.reply_text(messages.get(result.state, '⚠️ Статус уточняется.'))
    except ValueError:
        await q.message.reply_text('⚠️ Не удалось подтвердить условия или баланс. Генерация не запущена.')
    except Exception:
        g['log'].exception('quoted translation execution failed')
        await q.message.reply_text('⚠️ Статус уточняется. Не запускайте запрос повторно; обратитесь в поддержку.')
