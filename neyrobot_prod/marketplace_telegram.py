"""Telegram UI adapter for marketplace product intake (no billing or generation)."""
from .marketplace_studio import ProductProject, Stage, Output, Marketplace, select_output, select_marketplace, continue_after_references, upload_message
from .marketplace_navigation import back, cancel

STATE_KEY = 'marketplace_product_project'


def load(data):
    value = data.get(STATE_KEY) or {}
    return ProductProject(output=Output(value['output']) if value.get('output') else None,
                          marketplace=Marketplace(value['marketplace']) if value.get('marketplace') else None,
                          stage=Stage(value.get('stage', 'output')),
                          reference_ids=tuple(value.get('reference_ids', ())),
                          brief=value.get('brief', ''),
                          attributes_confirmed=bool(value.get('attributes_confirmed', False)),
                          approved=bool(value.get('approved', False)))


def save(data, project):
    data[STATE_KEY] = dict(output=project.output.value if project.output else None,
                           marketplace=project.marketplace.value if project.marketplace else None,
                           stage=project.stage.value, reference_ids=list(project.reference_ids),
                           brief=project.brief, attributes_confirmed=project.attributes_confirmed,
                           approved=project.approved)


def buttons(project):
    if project.stage == Stage.OUTPUT:
        return [('Студийные фото', 'mp:output:photos'), ('Инфографика', 'mp:output:infographics'),
                ('Видео товара', 'mp:output:video'), ('Полный комплект', 'mp:output:complete')]
    if project.stage == Stage.MARKETPLACE:
        return [(name, 'mp:market:' + value) for name, value in
                [('Wildberries', 'wildberries'), ('Ozon', 'ozon'), ('Яндекс Маркет', 'yandex'),
                 ('Amazon', 'amazon'), ('Универсальный', 'generic')]]
    if project.stage == Stage.REFERENCES:
        return [('Добавить фото', 'mp:more'), ('Продолжить', 'mp:continue'),
                ('Назад', 'mp:back'), ('Отмена', 'mp:cancel')]
    if project.stage == Stage.REVIEW:
        return [('Характеристики верны', 'mp:confirm'), ('Назад', 'mp:back'), ('Отмена', 'mp:cancel')]
    if project.stage == Stage.APPROVAL:
        return [('Проверить задание', 'mp:preview'), ('Рассчитать стоимость', 'mp:quote'),
                ('Создать за указанную стоимость', 'mp:generate'), ('Отмена', 'mp:cancel')]
    return [('Отмена', 'mp:cancel')]


def prompt(project):
    if project.stage == Stage.OUTPUT:
        return '🛍 AI-карточка товара. Выберите результат.'
    if project.stage == Stage.MARKETPLACE:
        return 'Выберите маркетплейс.'
    if project.stage == Stage.REFERENCES:
        return upload_message(project)
    if project.stage == Stage.BRIEF:
        return 'Опишите товар текстом или голосом. Подтвердите его характеристики.'
    if project.stage == Stage.REVIEW:
        return ('Проверьте описание товара:\n\n' + project.brief +
                '\n\nФотографий: ' + str(len(project.reference_ids)) +
                '\nПодтвердите характеристики или вернитесь для исправления.')
    return ('Характеристики подтверждены. Можно проверить задание и запросить стоимость. '
            'Платная генерация пока отключена; средства не списываются.')


def apply_action(project, action):
    if action == 'cancel':
        return cancel()
    if action == 'back':
        return back(project)
    if action == 'more' and project.stage == Stage.REFERENCES:
        return project
    if action == 'confirm':
        from .marketplace_studio import confirm_attributes
        return confirm_attributes(project)
    if action in ('preview', 'quote', 'generate') and project.stage == Stage.APPROVAL:
        return project
    if action == 'finish' and project.stage == Stage.APPROVAL:
        raise ValueError('Генерация ещё не подключена. Проект сохранён; кредиты не списаны.')
    if action == 'continue':
        return continue_after_references(project)
    if action.startswith('output:'):
        return select_output(project, Output(action.split(':', 1)[1]))
    if action.startswith('market:'):
        return select_marketplace(project, Marketplace(action.split(':', 1)[1]))
    raise ValueError('Invalid marketplace action')


async def callback(update, context):
    query = update.callback_query
    raw = query.data or ''
    if raw.startswith('ent:brief:mp:'):
        action = raw.removeprefix('ent:brief:mp:')
    elif raw.startswith('mp:'):
        action = raw.removeprefix('mp:')
    else:
        return
    if STATE_KEY not in context.user_data:
        await query.message.reply_text('Проект уже закрыт. Начните новый через меню.')
        return
    if action == 'continue' and context.user_data.get('mp_album_last_photo_at'):
        import time
        if time.monotonic() - context.user_data['mp_album_last_photo_at'] < 3:
            await query.message.reply_text('Фотоальбом ещё загружается. Подождите несколько секунд и нажмите «Продолжить» снова.')
            return
    try:
        project = apply_action(load(context.user_data), action)
    except ValueError as error:
        await query.message.reply_text(str(error))
        return
    if action == 'quote':
        await quote_callback(update, context, project)
        return
    if action == 'generate':
        await generate_callback(update, context, project)
        return
    if action == 'preview':
        from .marketplace_generation import prepare_generation, build_product_image_prompt
        try:
            request = prepare_generation(project)
        except ValueError as error:
            await query.message.reply_text(str(error))
            return
        if request.output.value == 'video':
            await query.message.reply_text('Для видео нужен отдельный видеоконвейер. Генерация пока недоступна; кредиты не списываются.')
        else:
            try:
                preview = build_product_image_prompt(request)
            except ValueError as error:
                await query.message.reply_text(str(error))
                return
            await query.message.reply_text('Предпросмотр задания для генератора (без запуска и списания):\\n\\n' + preview)
        return
    if action not in ('preview', 'quote'):
        context.user_data.pop('mp_quoted_usd_cents', None)
        context.user_data.pop('mp_quote_fingerprint', None)
    if action == 'cancel':
        context.user_data.pop(STATE_KEY, None)
        context.user_data.pop('mp_last_album_id', None)
        context.user_data.pop('mp_album_status_message', None)
        context.user_data.pop('mp_album_last_photo_at', None)
    else:
        save(context.user_data, project)
        if action == 'continue':
            for key in ('mp_last_album_id', 'mp_album_status_message', 'mp_album_last_photo_at', 'mp_quoted_usd_cents', 'mp_quote_fingerprint'):
                context.user_data.pop(key, None)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data='ent:brief:' + data)] for label, data in buttons(project)])
    await query.message.reply_text(prompt(project), reply_markup=keyboard)


async def receive_photo(update, context):
    """Return False when this update belongs to another bot workflow."""
    from .marketplace_studio import add_references
    if STATE_KEY not in context.user_data or not update.message or not update.message.photo:
        return False
    project = load(context.user_data)
    if project.stage != Stage.REFERENCES:
        return False
    try:
        project = add_references(project, (update.message.photo[-1].file_id,))
    except ValueError as error:
        await update.message.reply_text(str(error))
        return True
    save(context.user_data, project)
    album = getattr(update.message, 'media_group_id', None)
    if album:
        import time
        context.user_data['mp_album_last_photo_at'] = time.monotonic()
    if album and context.user_data.get('mp_last_album_id') == album:
        status_id = context.user_data.get('mp_album_status_message')
        if status_id:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            try:
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_id, text=prompt(project), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data='ent:brief:' + action)] for label, action in buttons(project)]))
            except Exception:
                pass
        return True
    if album:
        context.user_data['mp_last_album_id'] = album
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    markup = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data='ent:brief:' + action)] for label, action in buttons(project)])
    sent = await update.message.reply_text(prompt(project), reply_markup=markup)
    if album and sent:
        context.user_data['mp_album_status_message'] = sent.message_id
    return True


async def receive_text(update, context):
    """Consume text only while the marketplace wizard awaits a brief."""
    if not update.message or not update.message.text:
        return False
    return await receive_transcript(update, context, update.message.text)


async def receive_transcript(update, context, transcript):
    """Accept recognized voice text through the same validation as typed text.

    Speech-to-text remains the host application's responsibility; this function
    must be called only after a successful transcription.
    """
    from .marketplace_studio import set_brief
    if STATE_KEY not in context.user_data or not update.message:
        return False
    project = load(context.user_data)
    if project.stage != Stage.BRIEF:
        return False
    try:
        project = set_brief(project, transcript)
    except ValueError as error:
        await update.message.reply_text(str(error))
        return True
    save(context.user_data, project)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    markup = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data='ent:brief:' + action)] for label, action in buttons(project)])
    await update.message.reply_text(prompt(project), reply_markup=markup)
    return True


def start_project(user_data):
    """Start a fresh product-card draft; explicit entrypoint for the host menu."""
    project = ProductProject()
    for key in ('mp_last_album_id', 'mp_album_status_message', 'mp_album_last_photo_at'):
        user_data.pop(key, None)
    save(user_data, project)
    return project


def is_active(user_data, stage=None):
    """Gate shared photo/text/voice handlers without stealing unrelated updates."""
    if STATE_KEY not in user_data:
        return False
    return stage is None or load(user_data).stage == stage


def clear_project(user_data):
    user_data.pop(STATE_KEY, None)
    for key in ('mp_last_album_id', 'mp_album_status_message', 'mp_album_last_photo_at'):
        user_data.pop(key, None)


async def quote_callback(update, context, project):
    """Quote only through a configured billing integration; never invent prices."""
    from .marketplace_generation import prepare_generation
    try:
        request = prepare_generation(project)
        if request.output.value == 'video':
            raise ValueError('Для видео нужен отдельный видеоконвейер.')
        if len(request.reference_file_ids) > 16:
            raise ValueError('Для генерации выберите не более 16 фотографий товара.')
        quote_service = context.bot_data.get('marketplace_quote_service')
        if quote_service is None:
            await update.callback_query.message.reply_text(
                'Расчёт стоимости пока недоступен. Кредиты не списаны.'
            )
            return
        quote = await quote_service(request=request, user_id=update.effective_user.id)
        if not isinstance(quote, int) or isinstance(quote, bool) or quote <= 0:
            raise ValueError('Сервис стоимости не вернул действительную цену в центах USD.')
        from .marketplace_quote import fingerprint
        context.user_data['mp_quoted_usd_cents'] = quote
        context.user_data['mp_quote_fingerprint'] = fingerprint(request)
        await update.callback_query.message.reply_text(
            f'Стоимость одной генерации: ${quote / 100:.2f} USD. '
            'Платная генерация пока отключена; средства не списаны.'
        )
    except (ValueError, RuntimeError) as error:
        await update.callback_query.message.reply_text(str(error))


async def generate_callback(update, context, project):
    """Explicit user-triggered generation, disabled unless every dependency is configured."""
    import os
    import uuid
    from .marketplace_generation import prepare_generation
    from .marketplace_quote import validated_quote_cents

    message = update.callback_query.message
    try:
        request = prepare_generation(project)
        amount = validated_quote_cents(context.user_data, request)
        if request.output not in (Output.PHOTOS, Output.INFOGRAPHICS):
            raise ValueError('Этот формат ещё не поддерживается платным генератором.')
        if len(request.reference_file_ids) > 16:
            raise ValueError('Максимум 16 референсов на одну генерацию.')
        if os.getenv('MARKETPLACE_PAID_GENERATION_ENABLED') != '1':
            raise ValueError('Платная генерация отключена администратором. Средства не списаны.')
        ledger = context.bot_data.get('marketplace_usd_ledger')
        provider = context.bot_data.get('marketplace_image_client')
        if ledger is None or provider is None:
            raise ValueError('Платёжный модуль или генератор не настроен. Средства не списаны.')
        # A user-specific lock avoids simultaneous callbacks charging for the same draft.
        lock = context.user_data.get('mp_generation_lock')
        if lock is None:
            import asyncio
            lock = asyncio.Lock()
            context.user_data['mp_generation_lock'] = lock
        if lock.locked():
            raise ValueError('Генерация уже выполняется. Дождитесь результата.')
        async with lock:
            from .marketplace_pipeline import generate_and_deliver
            await message.reply_text(f'Генерация началась. Стоимость: ${amount / 100:.2f} USD.')
            await generate_and_deliver(
                project=project, bot=context.bot, chat_id=update.effective_chat.id,
                provider_client=provider, credit_ledger=ledger,
                user_id=update.effective_user.id, quoted_credits=amount,
                quote_accepted=True, provider_enabled=True,
                job_id=uuid.uuid4().hex,
            )
            clear_project(context.user_data)
            context.user_data.pop('mp_quoted_usd_cents', None)
            context.user_data.pop('mp_quote_fingerprint', None)
            await message.reply_text('Готово. Изображение отправлено файлом без сжатия.')
    except (ValueError, RuntimeError) as error:
        await message.reply_text(str(error))
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Marketplace paid generation failed')
        await message.reply_text('Генерация завершилась ошибкой. Если средства были зарезервированы, операция требует проверки администратором.')
