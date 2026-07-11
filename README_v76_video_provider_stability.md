# v76 video provider stability

Сборка поверх v74/v75. WebApp не менялся. Основные правки — видео-провайдеры и UX ошибок.

## Что исправлено

1. Runway/Comet больше не показывает пользователю длинные JSON-ошибки.
2. При ошибках Runway `model_not_found`, `no available channel`, `Invalid URL`, `此模型已下架` бот быстро уходит в резервный Kling.
3. Добавлен circuit breaker: если Runway падает несколько раз подряд, он уходит в cooldown и следующие пользователи сразу идут на резерв.
4. Удалён `gen4.5` из дефолтного списка Runway image→video, потому что он часто отдаёт `model_not_found/no available channel`.
5. Добавлена команда `/diag_runway`.
6. Добавлен `/diag_runway reset` для сброса cooldown.
7. Добавлен `/diag_runway test` — реальный тест Runway по последнему фото пользователя. Может списать кредит у провайдера.
8. Ошибка Telegram `Query is too old and response timeout expired...` больше не должна вываливаться пользователю простынёй; устаревшие callback-кнопки игнорируются или просят открыть меню заново.
9. Добавлено мягкое предупреждение, если исходник похож на скриншот/кадр с рамками, а не на чистое фото.

## Что заменить в gpt5pro-bot

Переименовать и заменить:

```text
main_v76_video_provider_stability.py → main.py
requirements_v76_video_provider_stability.txt → requirements.txt
runtime_v76_video_provider_stability.txt → runtime.txt
render_v76_video_provider_stability.yaml → render.yaml
```

`premium.html` менять не обязательно, WebApp в этой сборке не менялся.

## ENV добавить/изменить

```env
RUNWAY_IMAGE2VIDEO_ENABLED=1
RUNWAY_USE_COMET=1
RUNWAY_COMET_CREATE_PATH=/runwayml/v1/image_to_video
RUNWAY_COMET_STATUS_PATH=/runwayml/v1/tasks/{id}
RUNWAY_API_VERSION=2024-11-06
RUNWAY_IMAGE2VIDEO_MODELS=gen4_turbo,gen3a_turbo,veo3.1_fast,veo3.1,veo3
RUNWAY_IMAGE2VIDEO_FAIL_FAST=1
RUNWAY_HIDE_TECH_ERRORS=1
RUNWAY_AUTO_FALLBACK_KLING=1
RUNWAY_TASK_NOT_EXIST_FALLBACK_S=45
RUNWAY_PROVIDER_FAIL_THRESHOLD=2
RUNWAY_PROVIDER_COOLDOWN_S=300
RUNWAY_PUBLIC_FALLBACK_TEXT=⚠️ Runway сейчас недоступен у провайдера. Переключаю на резервный Kling.
```

## Проверка после деплоя

```text
/version
/diag_video
/diag_runway
```

Реальный тест Runway:

1. Отправить чистое фото в бот.
2. Отправить `/diag_runway test`.

Если Runway недоступен, бот должен показать короткое сообщение и/или уйти на Kling без технической простыни.
