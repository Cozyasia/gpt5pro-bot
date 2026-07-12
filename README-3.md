# Neyro-Bot GPT 5 Studio v83

Версия: `v83-video-credits-chats-midjourney-2026-07-12`

## Что добавлено

### 1. Три движка для text→video

Пользователь получает выбор:

- **Sora 2 — только без людей**;
- **Kling**;
- **Runway**.

Если в промпте обнаружен человек или персонаж, Sora 2 автоматически скрывается. Для людей предлагаются Kling и Runway. Цена каждой кнопки рассчитывается по движку и длительности.

### 2. Midjourney через CometAPI

- команда `/mj <промпт>` или `/midjourney <промпт>`;
- ручной запуск из меню «Движки»;
- submit → polling → загрузка результата;
- режимы `relax`, `fast`, `turbo` через ENV;
- списание кредитов только после успешной отправки изображения.

### 3. Кредиты вместо USD

- **1 кредит = 1 ₽**;
- пользователь не видит внутреннюю себестоимость в долларах;
- розничная цена включает маржу через `GENERATION_PRICE_MULTIPLIER`;
- цена округляется через `GENERATION_PRICE_ROUND_TO`;
- перед генерацией сумма резервируется;
- после успешной выдачи результата резерв превращается в списание;
- при API-ошибке, модерации, таймауте или отсутствии файла резерв освобождается;
- зависшие резервы автоматически освобождаются по `CREDIT_RESERVATION_TTL_S`;
- `credit_ledger` хранит журнал `reserved / charged / released / released_timeout`.

### 4. До четырёх независимых чатов

В главной клавиатуре появились:

- `💬 Мои чаты`;
- `➕ Новый чат`.

Команды: `/chats`, `/newchat`.

Для каждого чата доступны продолжение, история, переименование и удаление. История хранится в SQLite и переживает перезапуск Render. Старые сообщения из таблицы `chat_memory` автоматически переносятся в первый виртуальный чат.

## Установка

1. Сделайте резервную копию текущего репозитория и `/data/subs.db`.
2. Замените файлы из этой сборки:
   - `main.py`
   - `engine.py`
   - `render.yaml`
   - `requirements.txt`
   - `runtime.txt`
   - `premium.html`
   - `README.md`
   - `env.sample`
3. Не загружайте реальные ключи в GitHub. Оставьте секреты в Render Environment или Secret Files.
4. Убедитесь, что Render Disk смонтирован в `/data`, а `DB_PATH=/data/subs.db`.
5. Выполните Manual Deploy → Clear build cache & deploy.

## Ключевые ENV

```env
CHAT_MEMORY_ENABLED=1
CHAT_MEMORY_TTL_DAYS=0
CHAT_MAX_CONVERSATIONS=4
CHAT_HISTORY_PAGE_SIZE=8

CREDIT_RUB_VALUE=1
GENERATION_PRICE_MULTIPLIER=2.0
GENERATION_PRICE_ROUND_TO=5
CREDIT_RESERVATION_TTL_S=10800

TEXT_VIDEO_ALLOW_RUNWAY=1
RUNWAY_USE_COMET=1
RUNWAY_COMET_CREATE_PATH=/runwayml/v1/image_to_video
RUNWAY_COMET_STATUS_PATH=/runwayml/v1/tasks/{id}
RUNWAY_API_VERSION=2024-11-06

MIDJOURNEY_ENABLED=1
MIDJOURNEY_MODE=fast
MIDJOURNEY_CREATE_PATH=/mj-fast/mj/submit/imagine
MIDJOURNEY_STATUS_PATH=/mj/task/{id}/fetch
MIDJOURNEY_UNIT_COST_USD=0.134
```

Полный набор приведён в `env.sample` и `render.yaml`.

## Проверка после деплоя

1. `/version` — должна отображаться v83.
2. `/diag_yookassa` — ключи, чек и способы оплаты.
3. `/balance` — только кредиты, без USD.
4. `/chats` — создать четыре чата, переключиться между ними, проверить разный контекст.
5. Создать пятый чат — бот должен попросить удалить один из четырёх.
6. `/mj cinematic villa in Koh Samui --ar 16:9` — получить изображение и одно списание.
7. Запросить видео без людей — увидеть Sora 2, Kling и Runway.
8. Запросить видео с человеком — Sora 2 должна исчезнуть.
9. Вызвать заведомо отклоняемый или ошибочный рендер — баланс не должен уменьшиться.
10. Успешно получить MP4 — в `credit_ledger` должна появиться одна запись `charged`, без двойного списания.

## Важно

Синтаксис Python и YAML проверен локально. Реальные end-to-end вызовы CometAPI, Runway, Midjourney, YooKassa и Telegram требуют ваших действующих ключей и выполняются после деплоя.
