"""Adapter for one short translated video with Kling lip synchronization.

This module has no Telegram dependency. The caller owns the quote UI and must
supply a verified pricing configuration and an explicit delivery receipt.
"""
from __future__ import annotations

import math
from . import translation_paid_service
from .translation_segments import kling_sync_segment, sync_translated_video


async def run_short_translation(*, db_path, request_id, user_id, source_video,
                                duration, language, quote,
                                transcribe_and_dub, publish, kling, deliver, charge_user=True):
    """Reserve, translate, synchronize, deliver and settle a single segment.

    The outer caller must display the same quote before invoking this function.
    ``kling`` receives an ``on_provider_state`` callback; only the submitted
    lip-sync task ID is recorded as the provider task. Uncertain failures retain
    the hold through the underlying ledger and must be reconciled separately.
    """
    try:
        duration = float(duration)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('invalid video duration') from exc
    if not math.isfinite(duration) or not 2 <= duration <= 10:
        raise ValueError('supported duration is 2–10 seconds')
    if not isinstance(source_video, bytes) or not source_video:
        raise ValueError('video is required')
    if not isinstance(language, str) or not language.strip() or len(language) > 80:
        raise ValueError('invalid target language')

    if not isinstance(quote, translation_paid_service.TranslationQuote) or quote.duration != duration:
        raise ValueError('confirmed quote does not match video')

    async def render(on_task):
        dubbed = await transcribe_and_dub(source_video, duration, language.strip())
        if not isinstance(dubbed, bytes) or not dubbed:
            raise RuntimeError('dubbed video unavailable')

        async def provider(video_url, audio_url, duration_ms):
            def state(name, value):
                if name == 'lip_sync_task_id':
                    on_task(str(value))
            return await kling(video_url, audio_url, duration_ms=duration_ms,
                               on_provider_state=state)

        async def segment(video, audio, duration_ms):
            return await kling_sync_segment(video, audio, duration_ms, publish, provider)
        return await sync_translated_video(dubbed, duration, segment)

    return await translation_paid_service.run_quoted(
        db_path, request_id, user_id, quote, render=render, deliver=deliver, charge_user=charge_user,
    )
