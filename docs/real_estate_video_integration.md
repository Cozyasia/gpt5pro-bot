# Real-estate video integration checklist (draft PR)

The wizard and Google Veo adapter are **not wired into production**. Do not merge until reviewed.

## Registration in the existing python-telegram-bot application

1. Add the button returned by `real_estate_video.menu_button()` to the existing main-menu inline keyboard. This must be done in the actual menu constructor in `main.py`, not in a second independent Telegram application.
2. During app initialization, call:

```python
from real_estate_video import register_real_estate_handlers
from real_estate_veo_adapter import make_google_veo_renderer
register_real_estate_handlers(app, renderer=make_google_veo_renderer(app.bot))
```

3. The generic production PHOTO/TEXT handlers may intercept wizard uploads. Inspect their groups and ensure wizard messages are routed exclusively to the active wizard before registering. Do **not** merge based only on this snippet.
4. The renderer returns a local MP4 path. Verify Telegram's configured local Bot API server and `reply_video` behavior.
5. Ensure `/data/real_estate_jobs` is persistent and files are cleaned up only after delivery.
6. Existing billing must be integrated **before** enabling paid generation for users. Do not call the renderer before price confirmation, authorization, and an idempotent debit/hold.
7. A single Veo shot supports **one photo and 8 seconds** in this draft. Multi-photo, Kling, Seedance, 10/20/30 seconds, and FFmpeg concatenation are not yet connected to a paid provider.
8. Run `python -m unittest tests.test_real_estate_video`, a Telegram callback/photo flow test, a dry-run with mocked Google client, and one owner-authorized paid canary.
9. Review Google Veo model availability and input payload against current API contract before paying for a test.
10. Keep this PR draft until full end-to-end tests and billing checks pass.

## Operational safety

Google operation names are saved in `operation.txt`. On ambiguous POST outcome, do not resubmit automatically. On poll failure, reconcile the existing operation before any new paid submission.
