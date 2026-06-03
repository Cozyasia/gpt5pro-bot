GPT5PRO BOT v49-comet-bria-bg-upscale

Состав комплекта:
- main.py — обновлённый бот v49
- render.yaml — Render Blueprint с ENV под Comet Bria remove-background и increase-resolution
- requirements.txt — зависимости без rembg/onnxruntime
- env.sample — адаптированный env-файл под v49

Главные изменения:
1) Удаление фона через Comet bria/remove-background.
2) Замена фона: сначала transparent PNG, потом локальная композиция через Pillow.
3) Улучшение разрешения через Comet bria/increase-resolution, 2x/4x.
4) Удалён нерабочий путь /bria/image/edit/remove_background.
5) COMET_BG_USE_TELEGRAM_URL=0 и COMET_UPSCALE_USE_TELEGRAM_URL=0, чтобы не отдавать Telegram file URL с токеном бота во внешний API.

Деплой:
1) Заменить main.py, render.yaml, requirements.txt, env.sample в репозитории.
2) В Render проверить COMET_API_KEY, BOT_TOKEN, PUBLIC_URL, OPENAI_API_KEY.
3) Деплой.
4) Проверить /version.
5) Загрузить фото и проверить: удалить фон, заменить фон, улучшить 2x, улучшить 4x.

После успешного теста можно выключить подробные ошибки в чат:
COMET_BG_DEBUG_TO_CHAT=0
COMET_UPSCALE_DEBUG_TO_CHAT=0
