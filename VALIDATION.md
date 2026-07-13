# VALIDATION — v91 commercial pricing

## Compile

```bash
python -m py_compile main.py engine.py runway_official.py secret_loader.py presentation_studio.py
```

## Version

```text
/version
```

Expected:

```text
v91-commercial-pricing-midjourney-2026-07-13
```

## Price command

```text
/prices
```

Expected key values:

- OpenAI Images: 10 credits
- Midjourney Fast: 15 credits
- Sora 2 / 5 sec: 100 credits
- Kling / 5 sec: 50 credits
- Runway Gen-4.5 / 5 sec: 120 credits

## Image chooser

Send by text or voice:

```text
создай кинематографичное изображение готического замка
```

Expected:

- Auto button resolves to Midjourney;
- OpenAI Images and Midjourney are both available;
- exact price is shown on every button.

## Engines

Open `🧠 Движки`.

Expected:

- `🎨 Midjourney изображения` button;
- `💰 Цены генераций` button;
- Midjourney description explains CometAPI and `/mj`.

## Runway

```text
/diag_runway auth
```

Expected: official key accepted and source is Secret File.
