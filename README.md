# GPT5 Bot v67 — final webapp text + logo fallback fix

Основа: рабочая v66/v65.

## Что добавлено/исправлено

1. Обновлено описание WebApp / «Меню ботов»:
   - фраза «семь нейросетей — один бот» заменена на «мультимодельный нейро-бот»;
   - добавлены новые режимы: фото→видеоклип с музыкой, клип с вокалом для 1 человека, видео по тексту/голосу, AI-селфи, FaceSwap, Photoroom, Suno, CometAPI;
   - расширен блок «Под капотом» и FAQ.

2. Исправлено создание логотипа:
   - сначала пробуется старый image route;
   - затем Comet `/v1/images/generations`;
   - если внешние image-провайдеры недоступны, включается локальный PNG-fallback на Pillow, чтобы пользователь не получал тупик «Не удалось создать изображение».

3. В меню «Развлечения» в быстром меню добавлены:
   - 🎤 Клип с вокалом (1 человек)
   - 🎬 Видео по тексту/голосу

## Файлы

Для загрузки в GitHub/Render корень проекта должен содержать:

- `main.py`
- `requirements.txt`
- `render.yaml`
- `runtime.txt`
- `env.sample`
- `premium.html` — HTML мини-приложения / описания бота
- `README.md`

## Новые ENV для логотипа

```env
COMET_IMAGE_GEN_MODEL=gpt-image-1
COMET_IMAGE_GEN_PATH=/v1/images/generations
COMET_IMAGE_GEN_TIMEOUT_S=180
LOGO_LOCAL_FALLBACK=1
```

## Проверка после деплоя

```text
/version
/diag_video
/diag_suno
```

В `/version` должно быть:

```text
v67-final-webapp-logo-fix-2026-07-10
```
