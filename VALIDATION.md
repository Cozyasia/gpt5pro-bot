# Validation — Neyro-Bot v86

Дата проверки: 2026-07-13

## Выполнено

- `python -m py_compile main.py presentation_studio.py engine.py` — успешно.
- Импорт `main.py` с тестовыми ENV — успешно.
- `build_application()` — 56 зарегистрированных обработчиков.
- `render.yaml` разобран PyYAML — успешно, 264 ENV-записи.
- Извлечение бренда из брифа `марки Aldunenkoff` — результат `Aldunenkoff`.
- Product prompt содержит запрет псевдобукв и требование пустой этикетки.
- Text-sensitive запрос при выборе Midjourney маршрутизируется в OpenAI/Comet Images.
- Параллельный двойной запуск логотипов блокируется.
- При одном provider-результате мастер дополняет набор до 3 вариантов.
- Смоделирован сбой `reply_photo`: второй вариант отправлен документом, первый и третий не потеряны.
- Состояние проекта после генерации — `awaiting_logo_selection`.
- Тестовый PPTX и PDF собраны из единого проекта — успешно.
- Runway direct-first: сформирован запрос `gen4.5`, `POST /v1/image_to_video`, без `promptImage`, ratio `1280:720`.
- Runway Comet 503/model_not_found: сырой JSON скрыт, вызван Kling fallback.
- Кредитная обёртка сохранена для финального рендера и генераций с успешным результатом.

## Не запускалось

Реальные production-запросы к Runway, CometAPI, Kling, Midjourney, OpenAI Images, Telegram и YooKassa не выполнялись без пользовательских ключей.

## Важное ограничение

Ошибка `no available channel for ... runway-video` означает отсутствие активного Runway-канала у Comet в момент запроса. Код не может создать отсутствующий канал, поэтому v86 решает это official-first маршрутом и автоматическим Kling fallback.
