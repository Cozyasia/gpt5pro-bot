# v144 — provider-safe scene generation

Version: `v144-scene-provider-schema-retry-2026-07-21`

## Production failures fixed

1. Gemini received `auto`, `-` or another unsupported aspect value inside `generationConfig.responseFormat.image.aspectRatio`, returning HTTP 400.
2. OpenAI occasionally returned an empty or crowd-heavy scene plate; v143 correctly rejected it, but the pipeline had only one OpenAI attempt and no plate-specific rescue.

## New scene contract

- Aspect ratios are normalized to a supported value; unknown values become `4:5`.
- Gemini tries, in order:
  1. `responseFormat.image.aspectRatio + imageSize`;
  2. `responseFormat.image.aspectRatio`;
  3. `responseModalities=[IMAGE]` without explicit image format.
- Gemini, OpenAI and optional FLUX generate private, low-clutter scene plates with exactly one close adult man on the right and a clean left compositing zone.
- OpenAI creates two controlled scene candidates by default.
- If no plate survives, one strict OpenAI/Gemini rescue round runs.
- A local face detector result of zero is not accepted blindly: independent Vision QC must confirm exactly one visible right-side foreground adult and no extra prominent people.
- v143 cutout, celebrity identity, final two-face layout and natural-composite gates remain enabled and fail closed.
- No Nano Banana through Comet is added.

## Diagnostic commands

```text
/diag_selfie_v144
/diag_celebrity_flow
/diag_brand
```

Important fields:

```text
aspect_requested
aspect_normalized
gemini_schema_attempts
plate_attempts
scene_candidates
failure_class
errors
```

## Manual test

1. Confirm `/version` returns `v144-scene-provider-schema-retry-2026-07-21`.
2. Start Celebrity Selfie with one frontal user selfie and an optional second reference angle.
3. Select a catalog celebrity.
4. Test each preset: Premiere, Restaurant, Yacht, Exhibition, Red Square.
5. Verify Gemini no longer returns an invalid `aspect_ratio` HTTP 400.
6. Verify a result is delivered only when the final v143 checks still pass.
7. After any failure, run `/diag_selfie_v144` and inspect provider attempts.
