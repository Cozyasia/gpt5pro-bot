# v142 — Preserve-user Celebrity Selfie

Version: `v142-preserve-user-composite-2026-07-21`

## Production change

The normal Celebrity Selfie route no longer regenerates the user's face.

1. A scene plate is generated with one anonymous companion on the right and a deliberately empty left foreground.
2. Only the selected public person's identity is locked into the right-side face.
3. PhotoRoom removes the background from the user's real selfie. Local `rembg` is the fallback.
4. The original user cutout is composited into the left foreground with local-only scale, exposure matching, feathered edges and shadow.
5. User facial geometry is not synthesised. Generative whole-image cleanup is disabled by default.
6. If the preserve-user route cannot produce a structurally valid result, v140 remains a marked last-resort fallback.

## Result actions

- **Улучшить только лицо знаменитости** — accepted-result right-side refinement only.
- **Убрать рябь / улучшить качество** — deterministic local cleanup; generative whole-image cleanup is disabled by default.
- **Пересобрать только знаменитость** — keeps the accepted scene and user, reruns only the right-side identity refinement.
- **Вернуть предыдущий результат** — restores the prior accepted file.

The old **Усилить моё лицо** callback is intercepted and does not regenerate the user.

## Diagnostics

Run:

```text
/diag_selfie_v142
```

Expected markers:

```text
architecture=right_scene_plate+celebrity_identity+source_user_cutout+local_harmonisation
user_face_generation=disabled
user_pixel_lock=source_pixels_first
user_face_geometry_lock=required
photoroom=ready
legacy_fallback=-
```

A selected normal-route result must include:

```text
user_pixel_preserved=True
user_face_regenerated=False
```

If `legacy_fallback=used`, the preserve-user route failed and v140 produced the delivered result.

## Render requirements

The existing variables are reused:

```env
PHOTOROOM_API_KEY=...
PHOTOROOM_BASE_URL=https://sdk.photoroom.com
PHOTOROOM_REMOVE_PATH=/v1/segment
```

No Nano Banana through Comet is added.

## Manual test

1. `/version` must show `v142-preserve-user-composite-2026-07-21`.
2. Upload a clear frontal user selfie; optionally add a second angle.
3. Select a public person and a scene.
4. Confirm the progress text states that the user is cut out and composited without face regeneration.
5. Compare the user face with the source selfie: eye shape, nose, mouth, jaw, beard and asymmetry should remain source-faithful.
6. Run `/diag_selfie_v142` after the result.
7. Press **Улучшить только лицо знаменитости** and confirm the user and scene remain unchanged.
