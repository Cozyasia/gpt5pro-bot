# GPT5Pro Bot v56 — Comet-only AI Selfie build

This build keeps the full v35.6 logic plus:
- Talking avatar (Kling Avatar via Comet)
- Photo -> videoclip (Kling image-to-video via Comet)
- AI selfie with celebrity/character through Comet image-edit path

## New ENV for AI selfie via Comet

```env
AI_SELFIE_PROVIDER=comet
COMET_IMAGE_EDIT_MODEL=gemini-3-pro-image
COMET_IMAGE_EDIT_PATH=/v1/images/edits
COMET_IMAGE_EDIT_STATUS_PATH=
COMET_IMAGE_EDIT_TIMEOUT_S=180
AI_SELFIE_UNIT_COST_USD=0.20
AI_SELFIE_DEFAULT_ASPECT=4:5
AI_SELFIE_IMAGE_SIZE=2K
AI_SELFIE_MAX_SIDE=1536
AI_SELFIE_SEND_AS_DOCUMENT=1
AI_SELFIE_ALLOW_PUBLIC_FIGURES=1
```

Required existing key:

```env
COMET_API_KEY=...
COMET_BASE_URL=https://api.cometapi.com
```
