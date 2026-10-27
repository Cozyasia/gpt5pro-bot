"""Single-shot marketplace image pipeline with injected credit and media services.

Callers must provide a credit ledger implementing reserve/commit/release.
Never retry a paid provider call automatically.
"""
from __future__ import annotations

import asyncio
from io import BytesIO

from .marketplace_generation import ensure_paid_generation_ready, prepare_generation
from .marketplace_image_provider import generate_product_image
from .marketplace_telegram_media import download_reference_images


async def generate_and_deliver(*, project, bot, chat_id: int, provider_client,
                               credit_ledger, user_id: int, quoted_credits: int,
                               quote_accepted: bool, provider_enabled: bool = False,
                               model: str = "gpt-image-1", job_id: str | None = None):
    """Execute after explicit user consent; reserve before calling the provider.

    Ledger must provide async reserve(user_id, amount, idempotency_key),
    commit(reservation), release(reservation). Commit is only attempted after
    successful Telegram delivery. Provider costs incurred before delivery
    failure cannot be automatically recovered; surface failure to operator.
    """
    request = prepare_generation(project)
    ensure_paid_generation_ready(
        provider_enabled=provider_enabled,
        quoted_credits=quoted_credits,
        quote_accepted=quote_accepted,
    )
    if len(request.reference_file_ids) > 16:
        raise ValueError('Для одной генерации выберите не более 16 основных фотографий товара.')
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError('Для платной генерации необходим уникальный идентификатор задания.')
    references = await download_reference_images(bot, request)
    reservation = await credit_ledger.reserve(
        user_id=user_id,
        amount=quoted_credits,
        idempotency_key=f"marketplace:{user_id}:{job_id}",
    )
    if reservation is None:
        raise RuntimeError("Не удалось зарезервировать кредиты.")
    # An idempotent ledger must reject duplicate execution of a committed or
    # in-flight job; a reused reservation is NOT authorization to call the
    # paid provider a second time.
    if not getattr(reservation, 'newly_reserved', False):
        raise RuntimeError('Задание уже существует или резерв не подтверждён как новый.')
    provider_started = False
    delivered = False
    try:
        # OpenAI synchronous SDK call must not block Telegram's event loop.
        provider_started = True
        result = await asyncio.to_thread(
            generate_product_image,
            request,
            references,
            client=provider_client,
            model=model,
        )
        output = BytesIO(result)
        output.name = "product_card.png"
        message = await bot.send_document(
            chat_id=chat_id,
            document=output,
            caption="Готовая AI-карточка товара. Проверьте соответствие оригиналу.",
        )
        delivered = True
        await credit_ledger.commit(reservation)
        return message
    except Exception:
        if not provider_started:
            await credit_ledger.release(reservation)
        # Once the paid provider call has started, retain the reservation
        # for reconciliation: delivery failure does not undo provider cost.
        # A retry must use a new job or reconcile the existing job first.
        raise
