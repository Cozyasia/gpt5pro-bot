# Neuro-Bot GPT-5 — Telegram bot

Единый Telegram-бот для GPT-чата, документов, изображений, оживления фото, видео, озвучки, учебных/рабочих/медицинских сценариев и развлекательного контента.

## Текущая единая картина

В публичном описании и в меню используем одну формулировку:

**7 нейросетей/движков в одном боте:**

1. **GPT-5 / OpenAI text** — тексты, логика, код, документы, анализ изображений.
2. **Images** — генерация/правка изображений.
3. **Runway** — только оживление фото, особенно фото с людьми.
4. **Sora 2** — text→video и image→video для фото без людей.
5. **Kling** — text→video и photo→video, Reels/Shorts.
6. **Midjourney** — изображения, стили, референсы и промпты.
7. **Deepgram / STT/TTS** — распознавание речи, диктовка, озвучка.

**Luma временно скрыта** из меню и не используется, пока не решена оплата. В коде может оставаться как заготовка, но в пользовательском интерфейсе её не показываем.

## Режимы работы

- 🎓 **Учёба** — объяснение тем, задачи, конспекты из PDF/EPUB/DOCX, эссе, тесты, планы подготовки, аудиолекции.
- 💼 **Работа** — письма, документы, аналитика, брифы, ToDo, отчёты, презентационные материалы, таблицы.
- 🩺 **Медицина** — справочный разбор выписок, анамнеза, заключений, МРТ/КТ/снимков, результатов анализов. Не является диагнозом и не заменяет врача.
- 🔥 **Развлечения** — фото-мастерская, оживление фото, Reels/Shorts, мини-фильмы, сценарии, раскадровка, мемы, квизы.

## Что куда положить в репозитории

В корне репозитория должны быть:

```text
main.py            # основной бот; заменить на main_v24_ui_sync_final.py и переименовать в main.py
premium.html       # новая витрина/мини-приложение Telegram
README.md          # это описание проекта
render.yaml        # Render Blueprint, если деплоишь через blueprint
requirements.txt   # зависимости Python
runtime.txt        # версия Python
.env.sample        # пример переменных окружения, не секреты
```

`engine.py` трогать не нужно, если он сейчас не импортируется в `main.py` и бот уже работает без него.

## Как обновить мини-приложение Telegram

Сам бот на Render слушает webhook `/tg`. Статическую витрину лучше держать отдельно, чтобы она не конфликтовала с webhook-сервером.

### Вариант A — GitHub Pages

1. Добавить `premium.html` в корень репозитория.
2. GitHub → **Settings → Pages**.
3. Source: **Deploy from a branch**.
4. Branch: `main`, folder: `/root`.
5. Получить URL вида:
   `https://cozyasia.github.io/gpt5pro-bot/premium.html`
6. В Render добавить/обновить переменную:
   `WEBAPP_URL=https://cozyasia.github.io/gpt5pro-bot/premium.html`
7. В BotFather обновить кнопку меню:
   `/setmenubutton` → выбрать бота → указать тот же URL.

### Вариант B — отдельный Render Static Site

1. Создать новый сервис **Static Site**.
2. Подключить этот же репозиторий.
3. Publish directory: `.`
4. URL `premium.html` прописать в `WEBAPP_URL` и BotFather.

## Render: основные переменные окружения

Минимально обязательно:

```env
BOT_TOKEN=...
BOT_USERNAME=...
PUBLIC_URL=https://gpt5pro-bot.onrender.com
OPENAI_API_KEY=...
COMET_API_KEY=...
WEBAPP_URL=https://cozyasia.github.io/gpt5pro-bot/premium.html
```

Для видео через Comet:

```env
COMET_BASE_URL=https://api.cometapi.com
RUNWAY_USE_COMET=1
RUNWAY_COMET_CREATE_PATH=/runwayml/v1/image_to_video
RUNWAY_COMET_STATUS_PATH=/runwayml/v1/tasks/{id}
SORA_MODEL=sora-2
SORA_CREATE_PATH=/v1/videos
SORA_STATUS_PATH=/v1/videos/{id}
KLING_MODEL=kling-v1-6
KLING_CREATE_PATH=/kling/v1/videos/image2video
KLING_STATUS_PATH=/kling/v1/videos/image2video/{id}
KLING_TEXT_CREATE_PATH=/kling/v1/videos/text2video
KLING_TEXT_STATUS_PATH=/kling/v1/videos/text2video/{id}
```

## Проверка после деплоя

1. Render лог должен показать `Starting bot patch version: ui-sync-v24-SEVEN-ENGINES-WEBAPP-2026-05-23`.
2. `/start` должен писать про 7 нейросетей/движков и четыре режима: Учёба, Работа, Медицина, Развлечения.
3. Развлечения → Оживить фото: выбор Runway / Kling / Sora 2 без людей.
4. Голосовой или текстовый запрос «создай видео» должен предлагать **Sora 2** и **Kling**, не Runway.
5. Runway должен использоваться только после загрузки фото для оживления.
6. В мини-приложении должно быть: «Семь нейросетей — один бот», блоки про Учёбу, Работу, Медицину, Развлечения, Reels/Shorts/фильмы.
