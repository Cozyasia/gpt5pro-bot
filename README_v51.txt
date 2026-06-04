v51-comet-bg-channel-diagnostics-2026-06-04

Что исправлено:
1. PATCH_VERSION обновлён до v51.
2. Удалено скрытое принудительное добавление replicate-route в коде. Теперь если COMET_BG_REMOVE_PATHS=/v1/responses, бот реально использует только /v1/responses.
3. Bria-compatible route /bria/image/edit/* выключен по умолчанию через COMET_ALLOW_BRIA_COMPAT_ROUTES=0.
4. Добавлены кандидаты моделей:
   COMET_BG_MODEL_CANDIDATES=bria/remove-background,replicate/bria/remove-background
   COMET_UPSCALE_MODEL_CANDIDATES=bria/increase-resolution,replicate/bria/increase-resolution
5. render.yaml очищен от старых v48/replicate defaults.

Важно:
Если Comet возвращает:
no available channel for group default and model bria/remove-background
это означает проблему доступности модели/канала на стороне Comet для данного API key/group. Код не может включить этот канал программно. Нужно либо:
- добиться включения Bria/remove-background у Comet support;
- попробовать другой Comet key через COMET_BRIA_API_KEY;
- разрешить fallback на direct Bria/local/removebg.bd отдельной версией.
