# Neyro-Bot v88 — официальная интеграция Runway Developer API

Версия: `v88-runway-official-docs-2026-07-13`

Сборка подготовлена по текущей официальной документации Runway Developer API. Официальный Runway используется первым, канал CometAPI остаётся резервным, а Kling — последним fallback без повторного списания пользовательских кредитов.

## Что изменено

- добавлен отдельный модуль `runway_official.py`;
- ключ читается прежде всего из официальной переменной `RUNWAYML_API_SECRET`;
- text→video: `POST /v1/text_to_video`;
- compatibility fallback для Gen-4.5: `POST /v1/image_to_video` без `promptImage`, только если основной endpoint вернул `404/405`;
- image→video: `POST /v1/image_to_video`;
- локальные изображения передаются через ephemeral upload: `POST /v1/uploads` → `runway://...`;
- задачи проверяются через `GET /v1/tasks/{id}`;
- ключ и API-баланс проверяются через `GET /v1/organization`;
- обязательный заголовок `X-Runway-Version: 2024-11-06` отправляется во всех официальных запросах;
- polling выполняется не чаще одного раза в 5 секунд, с jitter и постепенным увеличением интервала;
- `THROTTLED` рассматривается как очередь, а не как ошибка;
- временные HTTP `429/502/503/504` автоматически повторяются;
- при неуспешном presigned upload создаётся новый upload slot;
- данные ключа не выводятся: диагностика показывает только безопасный fingerprint;
- пользовательская подпись результата содержит `Powered by Runway`;
- себестоимость считается по секундам: Gen-4.5 — `$0.12/с`, Gen-4 Turbo — `$0.05/с`, до розничной наценки бота.

## Какие файлы загрузить в репозиторий

Замените/добавьте все файлы из архива:

```text
main.py
runway_official.py          # новый обязательный файл
presentation_studio.py
engine.py
render.yaml
env.sample
premium.html
requirements.txt
runtime.txt
README.md
VALIDATION.md
```

`runway_official.py` должен находиться рядом с `main.py`.

## Настройка Render Environment — пошагово

### 1. Откройте Environment

```text
Render Dashboard
→ ваш сервис gpt5pro-bot
→ Environment
```

### 2. Добавьте новый секретный ключ

Нажмите **Add Environment Variable** и создайте:

```env
RUNWAYML_API_SECRET=key_ВАШ_НОВЫЙ_КЛЮЧ_NEYRO_BOT
```

Точное имя переменной:

```text
RUNWAYML_API_SECRET
```

Важно:

- вставьте полное значение, начинающееся с `key_`;
- не добавляйте кавычки;
- не оставляйте пробел в конце;
- не вставляйте имя ключа `Neyro_bot` — требуется именно секретное значение, которое Runway показал при создании;
- не сохраняйте секрет в GitHub, `main.py`, `render.yaml`, `env.sample` или Telegram;
- если старый `RUNWAY_API_KEY` остался в Render, удалите его после успешной проверки нового ключа. Код поддерживает его только как legacy fallback, но приоритет всегда у `RUNWAYML_API_SECRET`.

### 3. Проверьте несекретные переменные

При полной замене `render.yaml` эти значения уже будут заданы. Если вы не заменяете YAML, добавьте или обновите их вручную:

```env
RUNWAY_DIRECT_ENABLED=1
RUNWAY_DIRECT_FIRST=1
RUNWAY_BASE_URL=https://api.dev.runwayml.com
RUNWAY_API_VERSION=2024-11-06

RUNWAY_TEXT_CREATE_PATH=/v1/text_to_video
RUNWAY_TEXT_COMPAT_PATH=/v1/image_to_video
RUNWAY_I2V_PATH=/v1/image_to_video
RUNWAY_UPLOAD_PATH=/v1/uploads
RUNWAY_ORGANIZATION_PATH=/v1/organization

RUNWAY_TEXT_MODEL=gen4.5
RUNWAY_DIRECT_TEXT_MODELS=gen4.5
RUNWAY_DIRECT_I2V_MODELS=gen4.5,gen4_turbo

RUNWAY_DIRECT_RETRY_ATTEMPTS=4
RUNWAY_DIRECT_RETRY_BASE_S=1.5
RUNWAY_DIRECT_POLL_INTERVAL_S=5.0
RUNWAY_DIRECT_POLL_MAX_INTERVAL_S=15.0
RUNWAY_DIRECT_UPLOAD_ATTEMPTS=2
RUNWAY_DIRECT_DATA_URI_FALLBACK=1

RUNWAY_USE_COMET=1
RUNWAY_COMET_TEXT_MODELS=runway-video,gen4.5
RUNWAY_TEXT_FALLBACK_KLING=1
RUNWAY_AUTO_FALLBACK_KLING=1
RUNWAY_HIDE_TECH_ERRORS=1
TEXT_VIDEO_ALLOW_RUNWAY=1
```

### 4. Проверьте экономику

Рекомендуемые значения:

```env
USD_RUB=100
CREDIT_RUB_VALUE=1
GENERATION_PRICE_MULTIPLIER=2.0
GENERATION_PRICE_ROUND_TO=5
RUNWAY_COST_PER_SECOND_USD=0.12
RUNWAY_TURBO_COST_PER_SECOND_USD=0.05
RUNWAY_5S_COST_USD=0.60
```

При этих настройках 5 секунд Gen-4.5 имеют провайдерскую себестоимость около `$0.60`. При `USD_RUB=100` и коэффициенте `2.0` пользователю будет показано около 120 кредитов. Фактическая цена зависит от ваших текущих ENV.

### 5. Сохраните Environment

Нажмите **Save Changes**. Render может автоматически запустить новый deploy. Если этого не произошло, выполните:

```text
Manual Deploy
→ Clear build cache & deploy
```

## Проверка после деплоя

### Версия

```text
/version
```

Ожидается:

```text
v88-runway-official-docs-2026-07-13
```

### Конфигурация

```text
/diag_runway
```

Команда показывает:

- включён ли официальный маршрут;
- источник ключа;
- безопасный fingerprint;
- endpoints;
- модели;
- retry/polling/upload-настройки;
- состояние fallback.

### Проверка ключа и API-баланса без генерации

```text
/diag_runway auth
```

Ожидается:

```text
✅ Официальный Runway API доступен
...
```

Этот запрос читает сведения организации и не запускает видео.

### Реальный тест image→video

1. Отправьте чистое изображение в бот.
2. Выполните:

```text
/diag_runway test
```

Тест запускает настоящую генерацию и расходует API-кредиты Runway.

### Реальный тест text→video

1. Откройте `🔥 Развлечения`.
2. Нажмите `🎬 Видео по тексту/голосу`.
3. Отправьте текст или voice.
4. Выберите Runway.

При исправной настройке задача должна пойти в официальный Runway. Comet/Kling включатся только после временной недоступности официального маршрута.

## Значение основных ошибок

- `401` — ключ отсутствует, скопирован не полностью, имеет пробел, удалён или отключён;
- `400` — неверная модель, duration, ratio, prompt или входное изображение;
- `402` / insufficient credits — недостаточный API-баланс организации;
- `429` — достигнут tier/concurrency limit; бот повторяет запрос;
- `502/503/504` — временная ошибка Runway; бот повторяет запрос и при необходимости использует fallback;
- `THROTTLED` — задача принята и ожидает очередь, это не failure;
- `FAILED` / safety — задача отклонена модерацией или моделью, кредиты бота не фиксируются.

Для точной причины откройте в Runway Developer Portal:

```text
Manage → Request History
```

## Безопасность

- официальный ключ хранится только в Render Environment;
- бот не передаёт ключ в Telegram или браузер;
- `/diag_runway` показывает только первые/последние символы и длину;
- при случайной публикации ключ следует немедленно отключить в Runway и создать новый;
- не отправляйте значение ключа в чат поддержки или в этот диалог.
