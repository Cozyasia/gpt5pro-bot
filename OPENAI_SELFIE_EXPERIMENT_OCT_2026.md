# OpenAI Selfie Experiment — October 2026

This branch adds a removable, isolated OpenAI direct-edit lane.

## Production invariant

- main / V265 is untouched.
- Existing cs201/V265 callbacks and state are untouched.
- New callback namespace: oaiselfie:
- New command: /selfie_openai
- New state keys: openai_selfie_*
- Removing openai_selfie_exp_v1.py plus its guarded import in neyrobot_prod/__init__.py removes the experiment.

## Runtime

Required:
- OPENAI_API_KEY

Optional:
- OPENAI_SELFIE_EXPERIMENT_ENABLED=1
- OPENAI_SELFIE_IMAGE_MODEL=gpt-image-2.5-sunburst
- OPENAI_SELFIE_QUALITY=high
- OPENAI_SELFIE_MODERATION=auto
- OPENAI_SELFIE_TIMEOUT_S=300

The experiment reuses the existing three owner-managed hero JPEG references from the production catalogue but does not call the V265 geometry/FaceSwap pipeline.

Flow:
1. /selfie_openai
2. upload one original user photo
3. choose country and hero
4. choose preset scene or custom scene
5. OpenAI /v1/images/edits receives image[0]=original user photo and image[1..3]=hero references
6. output is delivered as a document

The prompt makes the original user photograph authoritative and asks the model to add the hero while preserving the user, pose, clothing, camera, background and lighting.

No production deployment/merge is performed by this experimental branch.
