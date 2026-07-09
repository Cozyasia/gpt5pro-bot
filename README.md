# GPT5Pro Bot v58 — Comet generateContent AI Selfie + fixed Avatar flow

Changes:
- AI selfie is routed through Comet Gemini/Nano Banana generateContent endpoint, not /v1/images/edits.
- Removed stale Gemini direct key references.
- Talking avatar flow is now sequential: portrait -> voice selection -> text -> Kling Avatar.
- If user sends voice/audio while avatar flow is active, it is used as real voice input for lip-sync.

Required ENV updates:
```env
AI_SELFIE_PROVIDER=comet
COMET_IMAGE_EDIT_MODEL=gemini-2.5-flash-image-preview
COMET_IMAGE_EDIT_FALLBACK_MODELS=gemini-2.5-flash-image-preview,gemini-2-5-flash-image-preview,gemini-2.5-flash-image,gemini-2-5-flash-image,gemini-3-pro-image
COMET_IMAGE_EDIT_PATH=/v1beta/models/{model}:generateContent
COMET_IMAGE_EDIT_TIMEOUT_S=240
COMET_IMAGE_EDIT_OPENAI_FALLBACK=0

AVATAR_TTS_DEFAULT_VOICE=nova
AVATAR_TTS_VOICES=nova,alloy,onyx,shimmer,fable
```
