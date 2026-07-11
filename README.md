# v73 — финальная бренд/маркетинг-сборка Neyro-Bot GPT 5 Studio

Основа: v72. Изменения минимальные и безопасные:

1. Бренд в коде: `Neyro-Bot GPT 5 Studio`.
2. Обновлены SEO/маркетинг-тексты для профиля Telegram:
   - `BOT_PUBLIC_NAME`
   - `BOT_SHORT_DESCRIPTION`
   - `BOT_DESCRIPTION`
   - `OPENROUTER_APP_NAME`
3. Приветствие `/start` адаптировано под формулировку AI-студии.
4. WebApp `premium.html` обновлён под новый бренд и список возможностей.

## Что заменить

### Репозиторий/сервис бота `gpt5pro-bot`
- `main_v73_neyrobot_gpt5_studio_marketing.py` → `main.py`
- `requirements_v73_neyrobot_gpt5_studio_marketing.txt` → `requirements.txt`
- `runtime_v73_neyrobot_gpt5_studio_marketing.txt` → `runtime.txt`
- `render_v73_neyrobot_gpt5_studio_marketing.yaml` → `render.yaml`, если используете render.yaml

### Репозиторий/сервис WebApp `gpt5pro-webapp`
- `premium_v73_neyrobot_gpt5_studio_marketing.html` → `webapp/premium.html`

## ENV для Render бота

```env
OPENROUTER_APP_NAME=Neyro-Bot GPT 5 Studio
BOT_PUBLIC_NAME=Neyro-Bot GPT 5 Studio
BOT_SHORT_DESCRIPTION=GPT-5, Sora 2, Kling, Runway, Midjourney, Suno: текст, фото, видео, музыка, аватар, Reels/Shorts в одном AI-боте.
BOT_DESCRIPTION=Neyro-Bot GPT 5 Studio — мультимодельная AI-студия в Telegram. GPT-чат, PDF/DOCX, фото и скриншоты, анализ документов, озвучка и распознавание речи, генерация изображений, логотипы, Midjourney-стиль, удаление/замена фона, замена лица, оживление фото, говорящий аватар, клип с вокалом для 1 человека, видео по тексту/голосу, Reels/Shorts, мини-фильмы, Sora 2, Kling, Runway, Suno-музыка. Выберите режим или просто напишите задачу.
AUTO_SET_BOT_PROFILE=1
```

## BotFather

BotFather можно настроить вручную теми же текстами. Если `AUTO_SET_BOT_PROFILE=1`, код также попробует обновить имя/описания сам через Telegram Bot API при старте.

## Рекомендованный слоган

`Neyro-Bot GPT 5 Studio — твоя AI-студия прямо в Telegram.`
