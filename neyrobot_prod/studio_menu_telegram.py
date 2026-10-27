"""Build safe Telegram buttons for validated Studio Mini App navigation.

Integration point in existing on_webapp_data (before payment dispatch):

    from neyrobot_prod.studio_menu_telegram import studio_navigation_markup
    navigation = studio_navigation_markup(raw)
    if navigation is not None:
        label, markup = navigation
        await update.effective_message.reply_text(label, reply_markup=markup)
        return

This does not synthesize CallbackQuery objects. A real user must click the
Telegram callback button, so the existing on_cb entry points remain intact.
Only enable the Mini App client after verifying the real Telegram launch mode.
"""
from .studio_menu_dispatch import navigation_response


def studio_navigation_markup(raw: str):
    """Return (text, InlineKeyboardMarkup) or None.

    Lazy import allows contract tests without telegram package installed.
    """
    navigation = navigation_response(raw)
    if navigation is None:
        return None
    route, title = navigation
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("Продолжить в боте", callback_data=route)]
    ])
    return title + "\nНажмите кнопку, чтобы открыть раздел.", markup
