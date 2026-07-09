# GPT5 Bot v63 — reliable full photo→music clip mode

This build keeps the existing bot logic, but changes the photo→music clip flow to a single reliable mode:

- only one mode for photo→clip: full clip with music
- video engine: Kling
- music engine: Suno
- result: one final MP4 only
- no fallback success without music
- no direct-link fallback for this flow
- longer wait window (5–15 min, configurable up to 20 min)
- clearer progress messages for the user
- background task mode remains enabled to reduce Telegram duplicate updates

## Files
- `main_v63_full_music_clip_reliable.py`
- `env_sample_v63_full_music_clip_reliable.txt`
- `requirements_v62_fast_background_photo_clip.txt`
- `render_v62_fast_background_photo_clip.yaml`
- `runtime_v62_fast_background_photo_clip.txt`

## Recommended ENV for full clip with music

```env
SUNO_ENABLED=1
SUNO_API_KEY=YOUR_KEY
SUNO_BASE_URL=https://api.cometapi.com
SUNO_CREATE_PATH=/suno/submit/music
SUNO_STATUS_PATH=/suno/fetch/{id}
SUNO_TIMEOUT_S=1200
SUNO_POLL_DELAY_S=5.0

PHOTO_CLIP_PIPELINE=1
PHOTO_CLIP_VIDEO_ENGINE=kling
PHOTO_CLIP_MUX_AUDIO=1
PHOTO_CLIP_BACKGROUND_TASK=1
PHOTO_CLIP_PARALLEL_STAGES=1
PHOTO_CLIP_DEFAULT_DURATION_S=15
PHOTO_CLIP_MAX_DURATION_S=30
PHOTO_CLIP_SUNO_FAST_TIMEOUT_S=900
PHOTO_CLIP_AUDIO_AFTER_VIDEO_WAIT_S=900
PHOTO_CLIP_TOTAL_USER_WAIT_S=1200
PHOTO_CLIP_SEND_BASE_IF_MUX_FAILS=0
PHOTO_CLIP_SEND_BASE_WHILE_MUSIC_PENDING=0
SUNO_AUTO_FOR_PHOTO_CLIP=1
PHOTO_CLIP_SOUND=0
```

## Endpoints to keep
- Kling create: existing `KLING_CREATE_PATH` from your current ENV/project
- Kling status: existing `KLING_STATUS_PATH` from your current ENV/project
- Suno create: `/suno/submit/music`
- Suno status: `/suno/fetch/{id}`

## Deploy
Use `main_v63_full_music_clip_reliable.py` as your main application file, keep the same requirements/render/runtime files as v62.
