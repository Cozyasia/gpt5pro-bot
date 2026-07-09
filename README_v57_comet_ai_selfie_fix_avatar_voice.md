# GPT5Pro Bot v57 — Comet AI Selfie Fix + Avatar Voice Selection

Changes:
- Fixed AI selfie Comet route: removed leftover `GEMINI_IMAGE_API_KEY` runtime reference.
- AI selfie now uses `COMET_API_KEY` + `COMET_IMAGE_EDIT_MODEL` + `COMET_IMAGE_EDIT_PATH`.
- Added talking avatar TTS voice selection buttons: Nova, Onyx, Alloy, Shimmer, Fable.
- Text-to-avatar uses selected `avatar_tts_voice`; direct MP3/WAV/M4A/AAC still uses the real uploaded audio.

Required new ENV:

```env
AVATAR_TTS_DEFAULT_VOICE=nova
AVATAR_TTS_VOICES=nova,alloy,onyx,shimmer,fable
AI_SELFIE_PROVIDER=comet
COMET_IMAGE_EDIT_MODEL=gemini-3-pro-image
COMET_IMAGE_EDIT_PATH=/v1/images/edits
COMET_IMAGE_EDIT_TIMEOUT_S=180
```

Existing required ENV:

```env
COMET_API_KEY=...
COMET_BASE_URL=https://api.cometapi.com
OPENAI_TTS_KEY=...
OPENAI_STT_KEY=...
```
