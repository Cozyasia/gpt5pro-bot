# Validation — Neyro-Bot v88

Версия: `v88-runway-official-docs-2026-07-13`

## Реализовано

- отдельный официальный REST-клиент `runway_official.py`;
- canonical secret: `RUNWAYML_API_SECRET`, legacy alias используется только как fallback;
- `Authorization: Bearer ...` и `X-Runway-Version: 2024-11-06`;
- `POST /v1/text_to_video` для text→video;
- compatibility retry через `/v1/image_to_video` без изображения только при `404/405`;
- `POST /v1/image_to_video` для image→video;
- `POST /v1/uploads` и `runway://` для пользовательских файлов;
- новый upload slot после неуспешной presigned-загрузки;
- data URI fallback только для файлов не более 5MB;
- `GET /v1/tasks/{id}` с polling от 5 секунд, jitter и backoff;
- поддержка `PENDING`, `RUNNING`, `THROTTLED`, `SUCCEEDED`, `FAILED`, `CANCELED`;
- retry только для transient HTTP `429/502/503/504` и transport errors;
- `GET /v1/organization` для read-only auth/balance diagnostic;
- безопасный fingerprint ключа;
- Gen-4.5 text→video и Gen-4.5/Gen-4 Turbo image→video;
- цена Runway по секундам;
- атрибуция `Powered by Runway`;
- Comet и Kling fallback без второго списания;
- мастер презентаций/каталогов v86 сохранён.

## Локально проверено

- компиляция всех Python-файлов;
- импорт `main.py` с тестовыми ENV;
- создание Telegram Application;
- разбор `render.yaml` без дублирующихся ключей;
- наличие обязательных Runway ENV;
- разбор `premium.html`;
- mocked organization request;
- mocked text task: create → PENDING/THROTTLED → SUCCEEDED;
- mocked ephemeral upload → image task → SUCCEEDED;
- классификация retryable/non-retryable ошибок;
- отсутствие очевидных production API secrets в релизе.

## Не проверено без вашего секрета

- реальная авторизация ключа `Neyro_bot`;
- реальный баланс и tier вашей Runway organization;
- фактическая Gen-4.5/Gen-4 Turbo генерация;
- реальные moderation failures и concurrency limits;
- списание API credits и доставка MP4 в production Telegram.
