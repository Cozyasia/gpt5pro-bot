# Star Selfie V204 recovery

This branch restores the production identity architecture requested after the Star Selfie rewrite regression.

## Pipeline

1. Gemini generates the complete scene from the user body reference and all 3-6 catalogue references of the selected hero.
2. Gemini is solely responsible for the hero identity, age, body, wardrobe, lighting and scene composition.
3. The face-swap provider runs exactly once after scene generation.
4. That pass transfers only the uploaded user face into principal face index 0 (the user on image-left).
5. The hero face is never sent through Face Swap, face restoration or a second generative redraw.

## Regression guard

`tests/star_selfie/test_pipeline_identity_routing.py` verifies that:

- every hero catalogue reference reaches the scene provider;
- Face Swap is called exactly once;
- the source is the uploaded user portrait;
- the destination is face index 0;
- hero Face Swap remains disabled.

## Deployment

Merge this branch only after CI passes. Render should then deploy the merge commit from `main`. The existing persistent character catalogue is not replaced or deleted.
