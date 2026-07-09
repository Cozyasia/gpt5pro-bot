# GPT5 Bot v53 — full v35.6 logic + Kling Avatar + Photo→VideoClip

Версия: `v53-full-v35.6-plus-avatar-photoclip-2026-07-09`

Эта сборка сделана не как урезанная v52, а как полная база `v35.6-bg-two-stage` с добавленными функциями:

- 🗣 **Говорящий аватар**: фото человека + текст / voice / audio → lip-sync video через Kling Avatar.
- 🎵 **Фото → видеоклип**: фото человека → Kling image→video с `sound:on` по умолчанию.
- Сохранена вся логика v35.6: двухэтапная замена фона, Photoroom, local/rembg fallback-флаги, FaceSwap PiAPI/Segmind, точный выбор лиц, Suno, live-search, память чата, бесплатные лимиты, медицина, презентации, PDF-каталоги, логотипы, ретушь, документы и платежная логика.

## Что загружать в репозиторий

Если используешь ZIP, внутри уже лежат правильные имена:

- `main.py`
- `render.yaml`
- `requirements.txt`
- `runtime.txt`
- `env.sample`
- `README.md`

Если берешь отдельные файлы, переименуй:

- `main_v53_full_logic_avatar_photoclip.py` → `main.py`
- `render_v53_full_logic_avatar_photoclip.yaml` → `render.yaml`
- `requirements_v53_full_logic_avatar_photoclip.txt` → `requirements.txt`
- `runtime_v53_full_logic_avatar_photoclip.txt` → `runtime.txt`
- `env_sample_v53_full_logic_avatar_photoclip.txt` → `env.sample`

## Новые ENV

```env
KLING_AVATAR_CREATE_PATH=/kling/v1/videos/avatar/image2video
KLING_AVATAR_STATUS_PATH=/kling/v1/videos/avatar/image2video/{id}
KLING_AVATAR_MODE=std
AVATAR_TTS_PROVIDER=openai
KLING_TTS_CREATE_PATH=/kling/v1/audio/tts
KLING_TTS_STATUS_PATH=/kling/v1/audio/tts/{id}
KLING_TTS_VOICE_ID=genshin_vindi2
KLING_TTS_LANGUAGE=en
KLING_TTS_SPEED=1.0
PHOTO_CLIP_SOUND=1
PHOTO_CLIP_MODE=pro
SUNO_AUTO_FOR_PHOTO_CLIP=0
AVATAR_UNIT_COST_USD=0.65
PHOTO_CLIP_UNIT_COST_USD=0.80
SUNO_UNIT_COST_USD=0.15
```

Нужны действующие ключи:

- `COMET_API_KEY` или `KLING_API_KEY` — для Kling Avatar и фото→клип.
- `OPENAI_TTS_KEY` — желательно для русской озвучки аватара через OpenAI TTS → MP3.
- `OPENAI_STT_KEY` — для Telegram voice, если нужно сначала распознать речь.
- `SUNO_API_KEY` или `COMET_API_KEY` — только если включишь `SUNO_AUTO_FOR_PHOTO_CLIP=1`.

## Как тестировать после деплоя

1. `/version` — должен показать `v53-full-v35.6-plus-avatar-photoclip-2026-07-09`.
2. `/diag_video` — должен показать строки Kling Avatar и Photo→clip.
3. Отправь фото человека → появятся кнопки:
   - `🗣 Говорящий аватар`
   - `🎵 Фото → видеоклип`
4. Для аватара: нажми `🗣 Говорящий аватар`, затем отправь текст или voice.
5. Для клипа: нажми `🎵 Фото → видеоклип`, затем напиши стиль: например `luxury fashion clip, плавное движение камеры, upbeat music, 9:16, 5 секунд`.

## Проверка

- `python -m py_compile main.py` — проходит.
- Сравнение функций с `v35.6-bg-two-stage`: не потеряна ни одна функция из v35.6; добавлено 22 новые функции для avatar/photo-clip.
- Сравнение ENV с `v35.6-bg-two-stage`: не потерян ни один ENV из v35.6; добавлены только новые avatar/photo-clip ENV.
