# AI Ad Studio — template engine specification

Status: initial implementation scaffold. Do not enable in production until integration tests pass.

## User flow
1. Choose Advertising Studio and category.
2. Select a visual style from the catalog.
3. Enter product name, description, selling points and target audience.
4. Upload 1–5 authorized product reference images; optional logo.
5. Choose aspect ratio (9:16, 16:9, 1:1), duration and Russian voiceover.
6. Preview a structured storyboard and estimated generation cost.
7. Confirm generation and credit charge.
8. Generate model-compatible scenes, verify product consistency, synthesize voice, compose music/titles and export MP4.

## Template contract
Each template has id, category, style, visual_reference_description, shot_plan, camera, lighting, editing, allowed_product_types, required_assets, negative_constraints, model_overrides, voiceover_tone and preview_asset_id.

The template NEVER hardcodes an advertised brand. Brand references used to describe a visual aesthetic must be removed from generation instructions. Product identity comes exclusively from user input and reference images.

## Adapter rules
- Seedance: validate current provider duration and image-to-video capabilities; split storyboard into supported clips.
- Kling: map reference assets, duration, camera instructions to verified API parameters.
- Runway: emphasize scene motion and concise camera instructions for image-to-video.
- Never claim 4K native output without checking actual provider support.
- Keep text, logos, Russian narration and music in compositing when model rendering is unreliable.
- If product reference fidelity fails, pause and request user review; don't charge repeatedly without approval.

## Quality and safety
Verify image ownership/authorization, no misleading product claims, exact brand and packaging details, no unauthorized endorsements, no unwanted extra products, no distorted logos, no invented product features. Preserve user data and existing bot accounting. All paid calls must be idempotent, logged and cost-confirmed.

## Rollout
Phase 1: schema, first 10 tested templates, preview and storyboard.
Phase 2: expand to 100 templates across agreed categories.
Phase 3: provider adapters, compositing, QA and owner-canary.
Phase 4: monitored rollout and credit billing.

## First template
ID: perfume-luxury-001
Category: fragrance
Style: luxury cinematic
Shots: dark silhouette reveal; macro product glass/packaging; elegant silk motion; premium pedestal hero shot; final stable packshot.
User variables: product_name, product_description, reference_images, logo, duration, aspect_ratio, language.
Camera: slow dolly-in, macro tracking, gentle orbit, symmetrical pullback.
Lighting: low-key warm rim lighting, physically plausible product reflections.
Constraints: preserve user-provided packaging, never substitute a reference brand, no generated text in footage, no flicker, no extra bottles.
Russian voiceover: generate from verified product facts and chosen brand voice, not fixed Chanel copy.
