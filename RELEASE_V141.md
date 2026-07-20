# Neyro-Bot v141 — accepted-result refinement and texture cleanup

Release: `v141-accepted-result-targeted-refinement-2026-07-20`

## Production fixes

- The exact file delivered to the user is saved as `accepted_result_path` and is the only base for every post-result edit.
- Raw selfies and intermediate scene plates are forbidden as refinement bases, preventing a yacht result from reverting to the source car/background.
- `Improve similarity` now selects the weaker side and edits one face only.
- Separate actions are available for the user face, public-person face, texture cleanup, and undo.
- Texture cleanup removes grain, moire, ringing and excessive sharpening separately from identity work.
- Every generated refinement must preserve the scene and the other identity; candidates are rejected when composition similarity, non-target identity, or texture quality regresses.
- Automatic weak-side repair runs only below 58/100 and is rejected when it adds artifacts or changes the scene.
- Initial identity insertion prefers OpenAI high-fidelity edits; PiAPI remains the fallback.
- Up to four previously accepted results are retained for undo.

## Result buttons

- `Улучшить сходство`
- `Убрать рябь / улучшить качество`
- `Усилить моё лицо`
- `Усилить лицо знаменитости`
- `Вернуть предыдущий результат`

Existing older `Улучшить сходство` buttons are intercepted and routed to v141 instead of the legacy scene-rebuild path.

## Diagnostics

Use any of:

- `/diag_selfie_v141`
- `/diag_celebrity_flow`
- `/diag_brand`

The card reports the accepted path/SHA, locked scene, provider order, target side, before/after identity scores, composition similarity, artifact metrics, safeguard decision and errors.

## Manual acceptance test

1. Generate a yacht result.
2. Press `Улучшить сходство`; the result must remain on the yacht and must not reuse the car/background from the source selfie.
3. Press `Убрать рябь / улучшить качество`; composition and both identities must remain stable while texture noise is reduced.
4. Press `Усилить моё лицо`; only the left/user face may change.
5. Press `Усилить лицо знаменитости`; only the right face may change.
6. Press `Вернуть предыдущий результат`; the immediately preceding accepted file must be restored without a provider call.
7. Run `/diag_selfie_v141` and verify `refinement_base=last_delivered_accepted_result_only` and `scene_lock=required`.
