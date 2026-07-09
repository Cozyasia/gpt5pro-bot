# GPT5Pro Bot v59 — AI-selfie timeout fix + clean UI

Based on v58. Changes:
- removed competitor wording from AI-selfie menu/help text;
- AI-selfie defaults changed to Comet generateContent, 1K, 1024px input, 600s timeout;
- first attempt is faster: fewer auth/model variants;
- compact retry after timeout;
- `/diag_video` shows AI-selfie timeout/max_side/size/fast settings;
- talking avatar flow from v58 is kept.

Recommended ENV:

```env
AI_SELFIE_PROVIDER=comet
COMET_IMAGE_EDIT_MODEL=gemini-2.5-flash-image
COMET_IMAGE_EDIT_FALLBACK_MODELS=gemini-2.5-flash-image,gemini-2.5-flash-image-preview,gemini-3.1-flash-image,gemini-3-pro-image,gemini-2-5-flash-image
COMET_IMAGE_EDIT_PATH=/v1beta/models/{model}:generateContent
COMET_IMAGE_EDIT_STATUS_PATH=
COMET_IMAGE_EDIT_TIMEOUT_S=600
COMET_IMAGE_EDIT_OPENAI_FALLBACK=0
AI_SELFIE_UNIT_COST_USD=0.20
AI_SELFIE_DEFAULT_ASPECT=4:5
AI_SELFIE_IMAGE_SIZE=1K
AI_SELFIE_MAX_SIDE=1024
AI_SELFIE_SEND_AS_DOCUMENT=1
AI_SELFIE_ALLOW_PUBLIC_FIGURES=1
AI_SELFIE_FAST_MODE=1
AI_SELFIE_RETRY_ON_TIMEOUT=1
```
