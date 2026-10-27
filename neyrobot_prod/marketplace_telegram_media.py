"""Download Telegram product reference photos in the user's chosen order.

No generation or credit mutation happens in this module.
"""
from __future__ import annotations

from io import BytesIO

from .marketplace_generation import GenerationRequest
from .marketplace_image_provider import ReferenceImage


async def download_reference_images(bot, request: GenerationRequest) -> tuple[ReferenceImage, ...]:
    if not request.reference_file_ids:
        raise ValueError("Не найдены фотографии товара.")
    if len(request.reference_file_ids) > 30:
        raise ValueError("Превышен лимит фотографий.")
    images = []
    for index, file_id in enumerate(request.reference_file_ids, start=1):
        telegram_file = await bot.get_file(file_id)
        stream = BytesIO()
        await telegram_file.download_to_memory(out=stream)
        content = stream.getvalue()
        if not content or len(content) > 20 * 1024 * 1024:
            raise ValueError(f"Фотография №{index} пуста или слишком велика.")
        images.append(ReferenceImage(filename=f"reference_{index}.jpg", content=content))
    return tuple(images)
