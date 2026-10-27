"""OpenAI image-edit adapter for verified marketplace product references.

This module does not bill users or expose a Telegram action. Callers must
complete credit reservation and explicit quote acceptance before invocation.
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from .marketplace_generation import GenerationRequest, build_product_image_prompt


@dataclass(frozen=True)
class ReferenceImage:
    filename: str
    content: bytes
    mime_type: str = "image/jpeg"


def _validate_references(references: tuple[ReferenceImage, ...]) -> None:
    if not references:
        raise ValueError("Нужна хотя бы одна фотография товара.")
    if len(references) > 30:
        raise ValueError("Допускается не более 30 фотографий.")
    for ref in references:
        if not ref.content or len(ref.content) > 20 * 1024 * 1024:
            raise ValueError("Фотография пуста или превышает 20 МБ.")
        if ref.mime_type not in ("image/jpeg", "image/png", "image/webp"):
            raise ValueError("Поддерживаются только JPEG, PNG и WebP.")


def _image_files(references: tuple[ReferenceImage, ...]):
    files = []
    for i, ref in enumerate(references):
        extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[ref.mime_type]
        stream = io.BytesIO(ref.content)
        stream.name = f"reference_{i + 1}.{extension}"
        files.append(stream)
    return files


def generate_product_image(
    request: GenerationRequest,
    references: tuple[ReferenceImage, ...],
    *,
    client,
    model: str = "gpt-image-1",
) -> bytes:
    """Edit using source images, never text-only generation.

    Client is injected for testability. No automatic retries: avoid accidental
    duplicate provider charges. API credentials are managed by the host.
    """
    _validate_references(references)
    if len(references) > 16:
        raise ValueError('Модель редактирования принимает не более 16 референсов за запрос. Выберите основные фотографии.')
    if len(references) != len(request.reference_file_ids):
        raise ValueError("Количество скачанных фотографий не совпадает с заданием.")
    if not model.strip():
        raise ValueError("Не задана модель генерации.")
    response = client.images.edit(
        model=model,
        image=_image_files(references),
        prompt=build_product_image_prompt(request),
        size="1024x1024",
    )
    data = getattr(response, "data", None)
    encoded = getattr(data[0], "b64_json", None) if data else None
    if not encoded:
        raise RuntimeError("Провайдер не вернул изображение.")
    try:
        result = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise RuntimeError("Некорректное изображение от провайдера.") from error
    if not result:
        raise RuntimeError("Провайдер вернул пустое изображение.")
    return result
