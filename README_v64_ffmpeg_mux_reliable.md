# GPT5 Bot v64 — reliable full music clip + ffmpeg mux fix

Changes from v63:
- Full photo→music clip still requires Suno audio before success.
- The final merge is local ffmpeg on Render.
- v64 makes merge fail-fast and reliable: copy-first MP4 remux, then ultrafast re-encode fallback.
- Adds ffmpeg mux timeout and diagnostic settings.
- Adds a user progress message before mux.

Changed ENV only:
```env
FFMPEG_MUX_TIMEOUT_S=180
FFMPEG_MUX_COPY_FIRST=1
FFMPEG_MUX_REENCODE_PRESET=ultrafast
FFMPEG_MUX_AUDIO_BITRATE=128k
```

Keep v63 full-music ENV:
```env
SUNO_TIMEOUT_S=1200
PHOTO_CLIP_SUNO_FAST_TIMEOUT_S=900
PHOTO_CLIP_AUDIO_AFTER_VIDEO_WAIT_S=900
PHOTO_CLIP_TOTAL_USER_WAIT_S=1200
PHOTO_CLIP_SEND_BASE_IF_MUX_FAILS=0
PHOTO_CLIP_SEND_BASE_WHILE_MUSIC_PENDING=0
```
