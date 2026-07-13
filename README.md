# Neyro-Bot v90 — image engine chooser + Runway Secret File support

Version: `v90-image-engine-choice-2026-07-13`

This release keeps the v89 Secret File support for Runway and adds a clearer image-generation UX:

- voice/text requests like “создай картинку ...” no longer silently run on an unclear engine;
- the bot now asks which image engine to use;
- the user can choose **Auto**, **OpenAI Images**, or **Midjourney**;
- after generation, the bot explicitly shows which engine was actually used.

## What changed

### 1) Engine choice for natural-language image requests
If a user writes or says:

- “создай изображение ...”
- “сгенерируй картинку ...”
- “нарисуй ...”

then the bot shows a chooser with comments:

- **Auto** — bot chooses the best route;
- **OpenAI Images** — precise objects, products, banners, logos, layouts, text-sensitive visuals;
- **Midjourney** — atmospheric, artistic, cinematic, fashion/editorial visuals.

### 2) Transparent result caption
The result now includes:

- engine used;
- short reason why it was chosen (for Auto mode);
- original prompt.

### 3) Quick commands remain
- `/img <prompt>` → direct fast OpenAI Images path;
- `/mj <prompt>` → direct Midjourney path.

## Where Midjourney is implemented

Midjourney is already integrated in the project and is implemented in these places:

- `main.py` — user flow, callbacks, and polling of the Midjourney task;
- `engine.py` — CometAPI wrapper methods for Midjourney;
- Environment variables in `env.sample`:
  - `COMET_API_KEY`
  - `MIDJOURNEY_ENABLED`
  - `MIDJOURNEY_MODE`
  - `MIDJOURNEY_CREATE_PATH`
  - `MIDJOURNEY_STATUS_PATH`

In this project, Midjourney works **through CometAPI** rather than through a native direct Midjourney API.

## Files to upload

Upload the entire release. Main files:

- `main.py`
- `engine.py`
- `runway_official.py`
- `secret_loader.py`
- `presentation_studio.py`
- `premium.html`
- `render.yaml`
- `env.sample`
- `requirements.txt`
- `runtime.txt`

## Render environment

### Required keys

Minimum important variables:

- `BOT_TOKEN`
- `PUBLIC_URL`
- `OPENAI_API_KEY` or your text provider settings
- `OPENAI_IMAGE_KEY` (or `OPENAI_API_KEY` if used for images too)
- `COMET_API_KEY` — required for Midjourney, Kling, Sora, some fallbacks
- `RUNWAYML_API_SECRET` — recommended via Secret File

## Render Secret File for Runway

Recommended when Render Environment form fails.

Open:

`Render Dashboard → gpt5pro-bot → Environment → Secret Files → Edit`

Create file:

```text
runway.env
```

Contents:

```env
RUNWAYML_API_SECRET=key_YOUR_OFFICIAL_RUNWAY_SECRET
```

Rules:

- no quotes;
- no spaces around `=`;
- one line only;
- do not commit to GitHub.

## Validation

After deploy:

1. `/version` → expected:

```text
v90-image-engine-choice-2026-07-13
```

2. Test voice/text image request:
   - send: `создай изображение граф Дракула на пике эльфовой башни`
   - expected: bot asks to choose **Auto / OpenAI Images / Midjourney**.

3. Test direct commands:
   - `/img red Ferrari in studio`
   - `/mj cinematic vampire lord, gothic tower`

4. Runway diagnostics:
   - `/diag_runway`
   - `/diag_runway auth`

If the key came from Secret File, expected source line contains:

```text
key_source=Secret File: runway.env
```
