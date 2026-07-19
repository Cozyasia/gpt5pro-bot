# v127 — Celebrity Selfie exact integration

## Корневая причина

Production-кнопка использует callback `fun:aiselfie`. v126 знала это значение, но её catch-all handler находился в одной общей PTB-группе. В python-telegram-bot в каждой группе выполняется только первый подходящий handler, поэтому другой runtime overlay мог занять группу раньше. Диагностическая команда при этом работала, а callback и фотография продолжали попадать в legacy-flow.

Дополнительно legacy-состояния `awaiting_ai_selfie_photo`, `awaiting_ai_selfie_prompt` и `ai_selfie_preset_prompt` не входили в очистку v126. После одного старого входа они заставляли общий photo handler снова открывать экран «Фото получено. Что сделать?».

## Исправления

- Явно перехватываются `fun:aiselfie`, `act:fun:aiselfie` и `pedit:aiselfie`.
- Добавлены два независимых точных handler-уровня с группами `-2000000000` и `-1900000000`.
- Перехватываются все `cs126:*`, `cs127:*` и `celeb:*` callback мастера.
- Фото, документы-изображения и текст блокируются от legacy-flow на всём протяжении активной сессии.
- Очищаются реальные legacy-ключи из `main.py`.
- Ошибки режима перехватываются отдельным error handler; общий текст «Упс, произошла ошибка» не отправляется.
- Сохраняются каталог 50+50, лицензированные reference packs, multi-image generation и «Улучшить сходство».

## Версия

`v127-celebrity-selfie-exact-integration-2026-07-19`
