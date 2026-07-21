# Neyro-Bot v145 — PiAPI-first Celebrity Identity Lock

Release: `v145-piapi-celebrity-lock-retry-2026-07-21`

## Production failure addressed

v144 successfully generated valid one-person scene plates, but the next stage
failed to lock the selected public-person identity:

- OpenAI returned structurally valid faces with similarity scores `15/100` or
  `0/100`;
- PiAPI returned HTTP 500 while receiving a one-face plate through
  `multi-face-swap`;
- the target image could be encoded with a long side of 2200 px, above PiAPI's
  documented sub-2048 px image constraint.

## Changes

### PiAPI-first identity route

The identity stage now uses this order:

1. PiAPI `face-swap` on the one-face right-side scene plate;
2. PiAPI indexed `multi-face-swap` with source `0` → target `0` as a compatibility
   fallback;
3. OpenAI high-fidelity targeted edit only when no PiAPI result passes strict QC.

### Provider-safe image preparation

- source reference face: maximum 1600 px;
- target scene plate: maximum 1900 px;
- every submitted PiAPI image remains below 2048 px;
- JPEG quality remains 96 to preserve identity detail.

### Multi-reference retries

Up to three ranked public-person references are tried independently. A provider
result is accepted only when it passes:

- one main foreground face on the right;
- no extra prominent people;
- visible target face;
- strict Vision identity score at or above the existing v143 threshold;
- the unchanged v143 final composite quality gates.

### User identity remains pixel-preserved

The user's frontal selfie continues through PhotoRoom/rembg and local compositing.
The user's face is not regenerated.

## Diagnostics

New command: `/diag_selfie_v145`

It reports provider order, PiAPI task type, reference index, max-side policy,
identity score, per-attempt failure reason and final selection.

## Deployment

`sitecustomize.py` loads v145 after all historical package and versioning hooks,
then the v145 builder wrapper re-applies the route after legacy Telegram builder
wrappers complete.
