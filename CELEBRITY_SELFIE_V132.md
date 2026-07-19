# Celebrity Selfie v132 — validated final-output pipeline

Release: `v132-celebrity-selfie-validated-final-output-2026-07-19`

## Production defects addressed

v132 fixes the failure mode where a provider-side input/reference sheet or a split-screen image could be mistaken for a finished celebrity selfie. It also prevents a late result from an old scene or celebrity selection from being published after the user changes the menu state.

## Pipeline

1. **Tolerant selfie preflight**
   - keeps v131 acceptance of ordinary clear waist-up and environmental portraits;
   - measurable resolution, brightness, contrast and sharpness remain hard gates;
   - the legacy local face detector remains advisory.

2. **Face-only scene references**
   - the full user photograph and its original background are no longer sent as scene inputs;
   - the user and celebrity references are cropped to identity-focused square portraits;
   - the scene model is instructed to create one continuous 4:5 smartphone frame with exactly two foreground people;
   - prompts explicitly prohibit collages, split screens, before/after layouts, borders and reference boards.

3. **Scene validation**
   - checks image integrity and resolution;
   - rejects extreme aspect ratios;
   - detects strong centre seams/split-screen layouts;
   - detects an original source photograph pasted beside another image;
   - optionally uses OpenAI Vision for scene/location and composition quality control.

4. **Mandatory two-person identity lock**
   - the user is source identity `0` and the celebrity is source identity `1`;
   - the target scene uses deterministic left-to-right face order;
   - PiAPI output is read only from explicit `data.output`/`output` fields;
   - input/config/reference payload fields are never treated as generated output.

5. **Final validation**
   - validates the PiAPI result again;
   - rejects technical source sheets and split-screen output;
   - rejects scene mismatch when Vision QC is available;
   - no intermediate draft is published on failure.

6. **Transactional Telegram flow**
   - one active generation per user/session;
   - duplicate scene-button presses do not create a second concurrent job;
   - scene and celebrity are snapshotted for the job;
   - a result is discarded if the live selection changes while providers are working;
   - provider details are stored in diagnostics but user-facing errors remain concise.

## Diagnostics

`/diag_celebrity_flow` should report:

```text
scene_input=face_crops_only
scene_validation=seam+aspect+face_count
piapi_output_parser=explicit_output_only
final_validation=local+vision_qc
duplicate_jobs=blocked
stale_results=blocked
raw_draft_delivery=blocked
```

## Testing contract

Production CI compiles all Python modules and runs the complete project unittest suite. Dedicated v132 tests cover:

- explicit PiAPI output extraction;
- refusal to fall back to provider input payloads;
- split-screen rejection;
- normal portrait acceptance;
- face-focused source ordering;
- duplicate-job blocking;
- fail-closed identity errors;
- stale scene/celebrity result blocking;
- sanitized public error messages.
