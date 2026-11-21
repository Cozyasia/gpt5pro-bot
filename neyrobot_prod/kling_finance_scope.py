"""Task-local reservation identity for Kling image-to-video execution."""
from contextvars import ContextVar

_finance = ContextVar('kling_finance', default=None)

class OutcomeUnknown(BaseException):
    """The provider or Telegram outcome is ambiguous; preserve the reservation."""

def current():
    return _finance.get()

async def run_scoped(action, kind, reference, user_id, feature):
    if feature not in {'image_to_video_kling', 'revive_photo_kling'}:
        return await action()
    token = _finance.set({'kind': kind, 'reference': reference, 'user_id': int(user_id)})
    try:
        return await action()
    finally:
        _finance.reset(token)

def raise_if_scoped():
    if current() is not None:
        raise OutcomeUnknown()
