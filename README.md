# v61 clean photo→music clip pipeline

Based on v60 avatar/faceswap fixes plus a new photo→music video pipeline.

## Key fixes
- Photo→videoclip now sends one final MP4 instead of link + duplicate files + inline preview.
- Kling is used only for the visual base clip.
- Suno is used for music/song generation.
- ffmpeg muxes/loops the video and music into one final MP4.
- If the user asks 20 seconds, the final file is assembled to roughly that target duration, even if Kling returns only a 5/10 second base clip.
- Native Kling `sound:on` is disabled for this flow because it was unreliable in tests.

## Required ENV
```env
COMET_API_KEY=...
COMET_BASE_URL=https://api.cometapi.com
SUNO_AUTO_FOR_PHOTO_CLIP=1
SUNO_API_KEY=  # optional; if empty code uses COMET_API_KEY
PHOTO_CLIP_PIPELINE=1
PHOTO_CLIP_VIDEO_ENGINE=kling
PHOTO_CLIP_DEFAULT_DURATION_S=15
PHOTO_CLIP_MAX_DURATION_S=30
PHOTO_CLIP_MUX_AUDIO=1
PHOTO_CLIP_SOUND=0
VIDEO_RESULT_SEND_AS_DOCUMENT=1
```

## Deployment
Use the flat ZIP or rename separate files:
- main_v61_clean_photo_music_clip_pipeline.py -> main.py
- requirements_v61_clean_photo_music_clip_pipeline.txt -> requirements.txt
- render_v61_clean_photo_music_clip_pipeline.yaml -> render.yaml
- runtime_v61_clean_photo_music_clip_pipeline.txt -> runtime.txt
