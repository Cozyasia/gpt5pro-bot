# Celebrity Selfie v133 — best-of-N production pipeline

## Release

`v133-celebrity-selfie-best-of-n-fallback-2026-07-19`

## Production changes

1. The service creates three independent scene candidates by default instead of trusting one render.
2. Candidates are validated and ranked by local image checks plus Vision composition checks.
3. Identity lock is attempted on the strongest two candidates by default.
4. OpenAI Images `/images/edits` is used as a second scene-provider fallback when Comet does not produce enough valid candidates.
5. Every preset has a scene-specific prompt contract: Red Square, restaurant, yacht, premiere and exhibition.
6. Final identity QA compares the user's reference, celebrity reference and final scene without asking Vision to identify anyone by name.
7. A failed render produces one actionable message only. The legacy second generic error card is suppressed.
8. The failure menu contains `Repeat this scene`, direct alternative scenes, `Change celebrity` and `Cancel`.
9. Repeated scene generation retains the chosen user photo, public person and scene.
10. Technical drafts, split screens, source sheets and stale results remain blocked.

## Default runtime values

```env
CELEBRITY_SCENE_CANDIDATES=3
CELEBRITY_IDENTITY_CANDIDATES=2
CELEBRITY_SCENE_PARALLEL=2
CELEBRITY_OPENAI_SCENE_FALLBACK=1
CELEBRITY_VISION_RANKING=1
CELEBRITY_IDENTITY_VISION_QC=1
CELEBRITY_MIN_IDENTITY_SCORE=58
CELEBRITY_EARLY_ACCEPT_SCORE=84
```

All values have safe in-code defaults; no Render Environment update is required for deployment.

## Provider chain

`Comet/Gemini scene candidates → OpenAI Images fallback → PiAPI multi-face identity lock → local and Vision QA`

## Diagnostic command

`/diag_celebrity_flow`

Expected contract:

```text
scene_candidates=3
identity_candidates=2
provider_chain=comet_best_of_n+openai_images_fallback+piapi_identity_lock
scene_templates=profile_specific
candidate_ranking=local+vision
identity_validation=vision_compare+local_qc
failure_ux=single_actionable_card
same_scene_retry=enabled
raw_draft_delivery=blocked
```

## User-visible failure UX

A rejected result is not sent. The user receives one message and can:

- repeat the same scene;
- select another preset immediately;
- change the public person;
- cancel the mode.

After two rejected attempts the bot recommends Premiere or Restaurant because those compositions normally keep both faces larger in frame.
