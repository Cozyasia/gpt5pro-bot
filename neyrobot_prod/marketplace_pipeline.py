"""Durable multi-output marketplace image generation and delivery."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from .marketplace_assets import build_infographic
from .marketplace_generation import ensure_paid_generation_ready, prepare_generation
from .marketplace_image_provider import generate_product_image
from .marketplace_pricing import MarketplaceQuote
from .marketplace_studio import Output
from .marketplace_telegram_media import download_reference_images
from .marketplace_usd_ledger import Reservation


_SHOT_PLANS = {
    Output.PHOTOS: (
        ("main", "главное изображение товара, ракурс три четверти, весь товар в кадре"),
        ("angle", "дополнительный естественный ракурс сбоку"),
        ("detail", "крупный план важной видимой детали и фактуры"),
    ),
    Output.INFOGRAPHICS: (
        ("main", "главное изображение товара с свободной областью справа для инфографики"),
    ),
    Output.COMPLETE: (
        ("main", "главное изображение товара, ракурс три четверти, весь товар в кадре"),
        ("angle", "дополнительный естественный ракурс сбоку"),
        ("detail", "крупный план важной видимой детали и фактуры"),
        ("lifestyle", "товар в уместной реалистичной сцене использования"),
    ),
}


def _validate_quote(request, quote: MarketplaceQuote) -> tuple[tuple[str, str], ...]:
    if not isinstance(quote, MarketplaceQuote):
        raise ValueError("Нет подтверждённого расчёта стоимости.")
    shots = _SHOT_PLANS.get(request.output)
    if shots is None:
        raise ValueError("Для видео нужен отдельный видеоконвейер.")
    expected_delivered = len(shots) + (1 if request.output in {Output.INFOGRAPHICS, Output.COMPLETE} else 0)
    if (
        quote.amount_cents <= 0
        or quote.provider_image_count != len(shots)
        or quote.delivered_image_count != expected_delivered
    ):
        raise ValueError("Расчёт стоимости не соответствует выбранному комплекту.")
    return shots


def _write_artifact(directory: Path, index: int, name: str, content: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{index + 1:02d}-{name}.png"
    temporary = destination.with_suffix(".tmp")
    with temporary.open("wb") as output:
        output.write(content)
        output.flush()
    temporary.replace(destination)
    return destination


async def generate_and_deliver(
    *,
    project,
    bot,
    chat_id: int,
    provider_client,
    credit_ledger,
    user_id: int,
    quote: MarketplaceQuote,
    quote_accepted: bool,
    provider_enabled: bool = False,
    job_id: str | None = None,
    artifact_dir: str = "/data/marketplace_jobs",
):
    """Generate the quoted set, persist it, deliver in order, then debit once."""
    request = prepare_generation(project)
    ensure_paid_generation_ready(
        provider_enabled=provider_enabled,
        quoted_credits=quote.amount_cents if isinstance(quote, MarketplaceQuote) else None,
        quote_accepted=quote_accepted,
    )
    shots = _validate_quote(request, quote)
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("Для платной генерации необходим уникальный идентификатор задания.")
    references = await download_reference_images(bot, request)
    key = f"marketplace:{user_id}:{job_id}"
    reservation = await credit_ledger.reserve(
        user_id=user_id,
        amount=quote.amount_cents,
        idempotency_key=key,
        provider_cost_usd=quote.provider_cost_usd,
        credits=quote.credits,
        expected_outputs=quote.delivered_image_count,
        metadata={
            "chat_id": int(chat_id),
            "job_id": job_id,
            "model": quote.model,
            "quality": quote.quality,
            "output": request.output.value,
            "marketplace": request.marketplace,
        },
    )
    if reservation is None:
        raise RuntimeError("Недостаточно средств на доступном балансе.")
    if not getattr(reservation, "newly_reserved", False):
        raise RuntimeError("Задание уже существует; повторный платный запуск заблокирован.")

    operation_id = f"openai:{job_id}:{int(time.time())}"
    if not await credit_ledger.mark_provider_started(
        reservation, operation_id=operation_id
    ):
        await credit_ledger.release(reservation)
        raise RuntimeError("Не удалось зафиксировать запуск AI-провайдера.")

    job_directory = Path(artifact_dir) / job_id
    artifacts: list[tuple[Path, str]] = []
    try:
        for index, (name, instruction) in enumerate(shots):
            content = await asyncio.to_thread(
                generate_product_image,
                request,
                references,
                client=provider_client,
                model=quote.model,
                quality=quote.quality,
                shot_instruction=instruction,
            )
            path = _write_artifact(job_directory, index, name, content)
            await credit_ledger.record_output(
                reservation, index=index, path=str(path)
            )
            artifacts.append((path, name))

        if request.output in {Output.INFOGRAPHICS, Output.COMPLETE}:
            infographic = await asyncio.to_thread(
                build_infographic, artifacts[0][0].read_bytes(), request.brief
            )
            index = len(artifacts)
            path = _write_artifact(job_directory, index, "infographic", infographic)
            await credit_ledger.record_output(
                reservation, index=index, path=str(path)
            )
            artifacts.append((path, "infographic"))
    except Exception as exc:
        await credit_ledger.mark_provider_failed(reservation, error=str(exc))
        raise

    messages = []
    try:
        for index, (path, name) in enumerate(artifacts):
            with path.open("rb") as document:
                message = await bot.send_document(
                    chat_id=chat_id,
                    document=document,
                    caption=(
                        f"AI-карточка товара {index + 1}/{len(artifacts)} — {name}. "
                        "Проверьте соответствие оригиналу."
                    ),
                )
            telegram_document = getattr(message, "document", None)
            await credit_ledger.mark_output_delivered(
                reservation,
                index=index,
                telegram_file_id=getattr(telegram_document, "file_id", None),
            )
            messages.append(message)
    except Exception as exc:
        await credit_ledger.mark_delivery_unknown(reservation, error=str(exc))
        raise

    if not await credit_ledger.commit(reservation):
        raise RuntimeError(
            "Результат доставлен, но списание не подтверждено. "
            "Операция сохранена для сверки; повторный запуск заблокирован."
        )
    return messages


async def recover_deliveries(*, bot, ledger) -> int:
    """Redeliver persisted outputs after a restart without a provider retry."""
    recovered = 0
    for job in await ledger.recoverable_jobs():
        reservation = Reservation(
            key=job.key,
            user_id=job.user_id,
            cents=job.cents,
            tx_id=job.tx_id,
            status=job.status,
            newly_reserved=False,
        )
        chat_id = job.metadata.get("chat_id")
        if not isinstance(chat_id, int):
            await ledger.mark_delivery_unknown(
                reservation, error="recovery metadata has no chat_id"
            )
            continue
        try:
            for output in job.outputs:
                if output.delivered:
                    continue
                path = Path(output.path)
                with path.open("rb") as document:
                    message = await bot.send_document(
                        chat_id=chat_id,
                        document=document,
                        caption=(
                            f"Восстановленная AI-карточка товара "
                            f"{output.index + 1}/{len(job.outputs)}."
                        ),
                    )
                telegram_document = getattr(message, "document", None)
                await ledger.mark_output_delivered(
                    reservation,
                    index=output.index,
                    telegram_file_id=getattr(telegram_document, "file_id", None),
                )
            if await ledger.commit(reservation):
                recovered += 1
        except Exception as exc:
            await ledger.mark_delivery_unknown(reservation, error=str(exc))
    return recovered
