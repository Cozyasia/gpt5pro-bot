# AI-видеообзор недвижимости

Production flow:

1. `REAL_ESTATE_VIDEO_ENABLED=1` arms the guarded router in the existing bot.
2. The user uploads 1–10 ordered photos and selects exterior, interior or full review.
3. `property_video_pipeline.plan_property_scenes()` assigns one reference image per scene.
4. Kling reuses the existing production Kling image-to-video transport, Veo uses the existing Google adapter, and Seedance uses the existing Comet transport.
5. Every accepted provider operation is written to the durable property-video journal.
6. FFmpeg normalizes all scene files and exports one MP4 on the Render persistent disk.
7. `credit_ledger` reserves retail capacity before submission and charges only after Telegram delivery.

Required Render settings:

- `REAL_ESTATE_VIDEO_ENABLED=1`
- `PROPERTY_VIDEO_PAID_ENABLED=1`
- `COMET_API_KEY` for Kling and Seedance
- `GEMINI_VIDEO_API_KEY` for Google Veo
- `DB_PATH=/data/subs.db`
- `PROPERTY_VIDEO_ROOT=/data/real_estate_jobs`

Recovery:

- `/propertyvideo_recover` re-delivers the latest saved MP4 without another provider call.
- A job with a known provider operation is never automatically resubmitted.
- A reservation is released only when the provider refusal is confirmed before an operation ID exists.

Verification commands:

```bash
python -m unittest tests.test_real_estate_video tests.test_real_estate_integration \
  tests.test_property_video_pipeline tests.test_property_video_billing -v
python -m py_compile real_estate_video.py real_estate_safe_router.py \
  real_estate_bootstrap.py real_estate_pipeline.py real_estate_veo_adapter.py \
  property_video_billing.py property_video_pipeline.py property_video_execution.py
```
