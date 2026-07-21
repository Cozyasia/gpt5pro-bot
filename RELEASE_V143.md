# Neyro-Bot v143 — strict composite quality gate

Version: `v143-strict-composite-quality-gate-2026-07-21`

## Production defect fixed

The first v142 production result demonstrated three unsafe acceptance paths:

1. a background-removal response containing a large opaque rectangle was treated as a valid user cutout;
2. a scene containing several unrelated prominent people was accepted even though the architecture required one right-side companion;
3. public-person and final-layout checks could return unknown/empty scores and still reach delivery because v142 forced the preserved-user score to at least 94.

This produced a visibly pasted rectangle from the source car interior, a mismatched ceremonial scene and no reliable selected-person likeness.

## v143 behavior

- Only the primary frontal selfie is eligible for compositing. The second angle remains a reference only.
- PhotoRoom uses `hd` by default and falls back to local rembg only after strict alpha validation.
- Alpha validation rejects excessive opaque coverage, insufficient transparency, rectangular bounding-box fill, opaque image borders and non-transparent corners.
- The user's detected face must remain inside the opaque subject mask.
- A scene plate must contain exactly one main foreground face on the right.
- A selected-person candidate is accepted only with a non-unknown strict vision score at or above 66/100.
- A final frame must contain exactly two main foreground faces in left-user/right-person order and compatible scale.
- Final vision QC requires all of the following:
  - exactly two main people;
  - preserved user matches the source selfie;
  - no rectangular patch;
  - no leaked source background;
  - coherent scale and lighting;
  - clean cutout edges;
  - visible companion face;
  - no extra prominent people;
  - requested-scene match;
  - naturalness at least 70/100.
- A source cutout touching the lower edge is anchored beyond the final canvas bottom so a hard horizontal torso boundary cannot float in the middle of the scene.
- Legacy v140 delivery fallback is disabled by default. A failed quality gate returns no image and should not charge the user.

## Diagnostics

Use:

```text
/version
/diag_selfie_v143
```

Expected version:

```text
v143-strict-composite-quality-gate-2026-07-21
```

A delivered result must show:

```text
user_pixel_preserved=True
user_face_regenerated=False
primary_selfie_only=True
legacy_fallback=-
visual_naturalness>=70
```

A bad segmentation or composite is expected to stop with a diagnostic run ID rather than send a preview.
