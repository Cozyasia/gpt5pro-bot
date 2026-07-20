# Celebrity Selfie v135 — native Gemini 3 identity pipeline

Version: `v135-celebrity-selfie-gemini3-native-identity-2026-07-20`

## Why v134 could still fail

v134 generated a placeholder two-person scene through CometAPI/Gemini 2.5 and then replaced both faces with PiAPI. This protected against collages, but the second rendering pass could lose hairline, head shape, skin texture, expression and coherent lighting. A provider or face-order miss could also reject the entire job.

## v135 pipeline

1. Select the strongest public-figure reference.
2. Send labelled identity references directly to Google Gemini 3 Pro Image.
3. Generate one seamless 4:5 two-person smartphone photograph natively at 2K.
4. Validate one frame, exactly two foreground people and no collage/split screen.
5. Compare both identities independently.
6. If the first result is not strong enough, try Gemini 3.1 Flash Image.
7. Use PiAPI only as a selective identity repair when the native scene is usable but one face is weak.
8. Keep v134 as the final provider fallback.

The final caption explicitly marks the image as AI-generated and states that it does not prove a real meeting, endorsement or partnership.

## Existing secret reused

No new secret is required. v135 uses the existing `GEMINI_IMAGE_API_KEY` already declared in `render.yaml`.

## Production defaults

```env
CELEBRITY_NATIVE_GEMINI=1
CELEBRITY_GEMINI_MODELS=gemini-3-pro-image,gemini-3.1-flash-image
CELEBRITY_GEMINI_MAX_REFERENCES=4
CELEBRITY_GEMINI_ASPECT=4:5
CELEBRITY_GEMINI_IMAGE_SIZE=2K
CELEBRITY_GEMINI_TIMEOUT_S=300
CELEBRITY_NATIVE_EARLY_ACCEPT_SCORE=74
CELEBRITY_NATIVE_REPAIR_BELOW=70
CELEBRITY_NATIVE_PIAPI_REPAIR=1
CELEBRITY_NATIVE_LEGACY_FALLBACK=1
CELEBRITY_NATIVE_UNIT_COST_USD=0.30
```

## Checks after deploy

1. `/version` must show `v135-celebrity-selfie-gemini3-native-identity-2026-07-20`.
2. `/diag_celebrity_flow` must show `pipeline=native_multi_reference`, both Gemini 3 models and `gemini_key=ready`.
3. Test a close, unfiltered single-person selfie in the `Премьера` or `Ресторан` scene first.
4. Verify one continuous photo, two distinct faces and the AI-generated disclaimer.
