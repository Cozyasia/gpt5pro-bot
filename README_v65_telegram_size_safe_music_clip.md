# v65 — Telegram 413 size fix for full music clip

Fixes the final upload error: `Request Entity Too Large (413)`.

The clip pipeline still requires music. v65 changes only the final ffmpeg mux/send stage:
- copy-first mux if the output is small enough;
- otherwise compressed 720p fallback;
- last-resort 540p fallback;
- target max output size is controlled by `FFMPEG_MUX_MAX_MB`;
- result is still one MP4 with Suno audio.

Recommended ENV additions/changes:

```env
FFMPEG_MUX_TIMEOUT_S=180
FFMPEG_MUX_COPY_FIRST=1
FFMPEG_MUX_REENCODE_PRESET=ultrafast
FFMPEG_MUX_AUDIO_BITRATE=128k
FFMPEG_MUX_MAX_MB=45
FFMPEG_MUX_CRF=32
FFMPEG_MUX_SCALE_HEIGHT=720
FFMPEG_MUX_FPS=24
```

Keep v63/v64 endpoints for Kling and Suno.
