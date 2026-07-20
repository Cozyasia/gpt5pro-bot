# Neyro-Bot v139 — Two-stage Celebrity Selfie

Release: `v139-two-stage-celebrity-selfie-2026-07-20`

## Architecture

v139 no longer asks one image model to solve composition and two exact identities in one pass.

1. **Scene plate** — direct Gemini Images, official OpenAI Images, and optional FLUX create anonymous two-person scene candidates. No celebrity or user identity references are included at this stage.
2. **LEFT identity** — the user's cropped reference is applied only to the left foreground face. PiAPI single-target face swap is attempted first; OpenAI high-fidelity edit is the independent fallback.
3. **RIGHT identity** — the selected person's reference is applied only to the right foreground face while the left face and the complete scene are preserved.
4. **Independent QC** — the left and right identities are scored separately. Structural validation remains mandatory.
5. **Weak-side repair** — only the lower-scoring side is retried.
6. **Delivery** — a high-confidence result is marked verified. A structurally valid lower-confidence result is delivered as a labelled preview instead of being hidden.

Nano Banana through Comet is intentionally not present in v139. Direct Gemini is used for scene candidates only.

## Hard gates

The result is blocked only when the file is invalid, the output is a collage/reference sheet/split screen, or two usable foreground faces are not present. Low identity confidence alone does not hide a structurally valid result.

## Diagnostics

After a run, use any of:

- `/diag_celebrity_flow`
- `/diag_selfie_v139`
- `/diag_brand`

The v139 diagnostic handler has a higher priority than all historical selfie handlers and reports:

- `run_id`
- scene and identity candidate counts
- readiness of PiAPI, OpenAI Images, direct Gemini and optional FLUX
- every stage with provider, duration, score or exact error class
- `failure_class`
- selected providers and separate user/public-person identity scores
- final delivery mode

No API keys or bearer tokens are printed.

## Acceptance test

1. `/version` must return `v139-two-stage-celebrity-selfie-2026-07-20`.
2. Open **Развлечения → Селфи со звездой**.
3. Upload a clear selfie. A close face photo is strongly preferred over a full-body restaurant photo.
4. Continue with one photo or add a second angle.
5. Select a catalog person and **Премьера**.
6. The progress message must mention scene first, then left and right identity lock.
7. On success, inspect the result and run `/diag_selfie_v139`.
8. On failure, copy the displayed diagnostic code and run `/diag_selfie_v139`; the output must identify the exact provider/stage instead of the old generic structural message.

## Environment

No new mandatory secret is required. Existing keys are reused:

- Gemini direct key for scene candidates
- OpenAI Images key for scene and high-fidelity identity fallback
- `PIAPI_API_KEY` for sequential one-face identity lock
- `BFL_API_KEY` remains optional

Important defaults are set in `neyrobot_prod/__init__.py`. `CELEBRITY_V139_IDENTITY_PROVIDERS=piapi,openai` can be overridden in Render if a provider needs temporary isolation.
