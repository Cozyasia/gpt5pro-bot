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
        return [('Завершить подготовку', 'mp:finish'), ('Отмена', 'mp:cancel')]
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
    return ('Характеристики подтверждены. Генерация и расчёт стоимости пока не подключены. '
            'Кредиты не списываются.')


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
    if action == 'finish' and project.stage == Stage.APPROVAL:
        return project
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
    try:
        project = apply_action(load(context.user_data), action)
    except ValueError as error:
        await query.message.reply_text(str(error))
        return
    if action == 'cancel':
        context.user_data.pop(STATE_KEY, None)
    else:
        save(context.user_data, project)
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
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    markup = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data='ent:brief:' + action)] for label, action in buttons(project)])
    await update.message.reply_text(prompt(project), reply_markup=markup)
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
    await update.message.reply_text(prompt(project))
    return True


def start_project(user_data):
    """Start a fresh product-card draft; explicit entrypoint for the host menu."""
    project = ProductProject()
    save(user_data, project)
    return project


def is_active(user_data, stage=None):
    """Gate shared photo/text/voice handlers without stealing unrelated updates."""
    if STATE_KEY not in user_data:
        return False
    return stage is None or load(user_data).stage == stage


def clear_project(user_data):
    user_data.pop(STATE_KEY, None)
