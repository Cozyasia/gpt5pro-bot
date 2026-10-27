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
                               model: str = "gpt-image-1"):
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
    references = await download_reference_images(bot, request)
    reservation = await credit_ledger.reserve(
        user_id=user_id,
        amount=quoted_credits,
        idempotency_key=f"marketplace:{user_id}:{chat_id}:{project.reference_ids}:{project.brief}",
    )
    if reservation is None:
        raise RuntimeError("Не удалось зарезервировать кредиты.")
    delivered = False
    try:
        # OpenAI synchronous SDK call must not block Telegram's event loop.
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
        if not delivered:
            await credit_ledger.release(reservation)
        # If delivery succeeded but commit failed, keep reservation for
        # reconciliation rather than refunding a delivered paid product.
        raise
