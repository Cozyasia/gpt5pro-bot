# VALIDATION — v90 image engine chooser

Version target: `v90-image-engine-choice-2026-07-13`

## 1. Version
Run:

```text
/version
```

Expected output contains:

```text
v90-image-engine-choice-2026-07-13
```

## 2. Image engine chooser from text
Send:

```text
создай картинку неоновый спорткар под дождём
```

Expected:

- bot does **not** immediately generate;
- bot asks which engine to use;
- buttons: **Auto**, **OpenAI Images**, **Midjourney**.

## 3. Image engine chooser from voice
Send a voice message like:

```text
сгенерируй изображение граф Дракула на пике эльфовой башни
```

Expected:

- voice is transcribed;
- bot asks which engine to use;
- after button click, generation starts;
- final caption includes the engine name.

## 4. Direct quick commands
### OpenAI
```text
/img product shot of a luxury watch on black background
```
Expected: direct generation through OpenAI Images.

### Midjourney
```text
/mj cinematic gothic castle, moonlight, dramatic fog
```
Expected: Midjourney flow starts directly.

## 5. Runway secret
Run:

```text
/diag_runway
/diag_runway auth
```

Expected when using Secret File:

```text
key_source=Secret File: runway.env
```
