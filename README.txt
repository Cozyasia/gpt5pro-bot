GPT5Pro Bot patch v50 — Comet Bria via /v1/responses

Что исправлено относительно v49:
1) Полностью отключены Bria-compatible routes /bria/image/edit/* по умолчанию.
   Причина: в live-тестах Comet возвращает 400 invalid relay mode на /bria/image/edit/remove-background.
2) Удаление фона теперь по умолчанию идёт только через:
   POST https://api.cometapi.com/v1/responses
   model: bria/remove-background
3) Улучшение разрешения теперь по умолчанию идёт только через:
   POST https://api.cometapi.com/v1/responses
   model: bria/increase-resolution
4) Replicate routes больше НЕ подставляются автоматически из кода.
   Они будут пробоваться только если вы явно добавите /replicate/... в COMET_BG_REMOVE_PATHS или COMET_UPSCALE_PATHS.
5) Добавлен COMET_ALLOW_BRIA_COMPAT_ROUTES=0.
   Не включайте его, пока Comet support письменно не подтвердит доступность /bria/image/edit/* для вашего аккаунта.
6) Диагностика теперь сохраняет несколько ошибок по маршрутам, а не только последнюю.

Минимальные Environment для Bria-функций:
BG_PROVIDER=comet
COMET_API_KEY=<ваш ключ Comet>
COMET_BASE_URL=https://api.cometapi.com
COMET_BG_MODEL=bria/remove-background
COMET_BG_REMOVE_PATH=/v1/responses
COMET_BG_REMOVE_PATHS=/v1/responses
COMET_BG_STATUS_PATH=/v1/responses/{id}
COMET_BG_STATUS_PATHS=/v1/responses/{id}
COMET_BG_USE_TELEGRAM_URL=0
COMET_BG_DEBUG_TO_CHAT=1
COMET_ALLOW_BRIA_COMPAT_ROUTES=0

COMET_UPSCALE_MODEL=bria/increase-resolution
COMET_UPSCALE_PATHS=/v1/responses
COMET_UPSCALE_STATUS_PATHS=/v1/responses/{id}
COMET_UPSCALE_DEFAULT_FACTOR=2
COMET_UPSCALE_USE_TELEGRAM_URL=0
COMET_UPSCALE_DEBUG_TO_CHAT=1

Важно удалить из Render Environment старые значения:
/bria/image/edit/remove-background
/bria/image/edit/remove_background
/bria/image/edit/increase-resolution

После деплоя проверить /version. Должно быть:
v50-comet-responses-bg-upscale-2026-06-03
