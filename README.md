# GPT5PRO Bot v69 — Vocal Clip Audio Safe

Исправление к v68 для режима **«Клип с вокалом / lip-sync (1 человек)»**.

## Что было
Иногда Suno возвращал длинный трек на 2–4 минуты. Дальше бот отправлял весь MP3 в Kling Avatar. На коротких треках это работало, а на длинных Comet/Kling мог принять задачу, но затем polling зависал и заканчивался ошибкой вида:

`Kling talking avatar: время ожидания вышло. Последний ответ: 404 Invalid URL (GET /v1/tasks/...)`

Это не ошибка Telegram и не ошибка Suno. Это нестабильность/ограничение этапа **Kling Avatar lip-sync** на длинном аудио.

## Что изменено
- Suno по-прежнему генерирует вокал.
- Перед отправкой в Kling Avatar бот локально через ffmpeg делает безопасный MP3-фрагмент.
- По умолчанию берутся первые ~65 секунд трека.
- Увеличен отдельный лимит ожидания для Kling Avatar lip-sync до 1800 секунд.
- Пользователь получает понятное сообщение, что для стабильного lip-sync используется короткий фрагмент.

## Что заменить в gpt5pro-bot

Переименовать и загрузить в корень репозитория:

- `main_v69_vocal_clip_audio_safe.py` → `main.py`
- `requirements_v69_vocal_clip_audio_safe.txt` → `requirements.txt`
- `render_v69_vocal_clip_audio_safe.yaml` → `render.yaml`
- `runtime_v69_vocal_clip_audio_safe.txt` → `runtime.txt`

`premium.html` менять не обязательно, если WebApp уже работает после v67/v68.

## Новые ENV

Добавить в Render Environment при необходимости:

```env
VOCAL_CLIP_MAX_AUDIO_S=65
VOCAL_CLIP_MIN_AUDIO_S=12
VOCAL_CLIP_KLING_MAX_WAIT_S=1800
```

Рекомендуемое значение `VOCAL_CLIP_MAX_AUDIO_S`: 45–75. Длиннее можно, но риск зависаний выше.

## Проверка

После деплоя:

```text
/version
/diag_video
```

В `/version` должно быть:

`v69-vocal-clip-audio-safe-2026-07-10`
