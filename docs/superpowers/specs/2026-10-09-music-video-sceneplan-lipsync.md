# Music-video ScenePlan and lip-sync specification

## Goal

For an approved vocal music-video request, compile the user's full music and video briefs once into the exact chronological scene contracts that the user reviews and Kling receives. Preserve world continuity across scenes and apply the approved Suno audio to visible-face intervals through Kling post-process lip-sync before final delivery.

## Required behavior

- Preserve the complete music and video briefs. Never truncate them silently in the approval UI.
- Represent the approved production contract as one immutable `ScenePlan` containing duration, aspect ratio, vocal start, and ordered scene contracts.
- Each scene contract contains its exact time range, current action, start state, end state, persistent world state, completed actions, unopened future count, and optional face-visible lip-sync interval.
- The approval renderer and provider prompts consume the same `ScenePlan`; approval must not show a different split from the one used for generation.
- Any change to duration, auto rewrite, voice rewrite, augmentation, or full rewrite creates a new plan and supersedes the old approval token.
- Future people, props, vehicles, locations, and seat assignments cannot appear before their first scene. Completed actions cannot restart.
- `SCENE_REFERENCE` is used only to create the initial keyframe. After scene 1, re-anchor from `FACE_FRONT`, `FACE_3Q`, `BODY_FULL`, and the previous continuation frame; do not send the original scene image as a composition reference.
- Vocal clips require at least one valid visible-face lip-sync interval. Each selected interval uses the matching slice of the approved Suno track and Kling `/kling/v1/videos/lip-sync` in `audio2video` mode.
- Lip-sync operates on 2–10 second video slices and preserves unsynchronised prefixes/suffixes when the vocal interval covers only part of a scene.
- If required lip-sync is unavailable, returns invalid media, or fails validation, stop the job and do not present the unsynchronised cinematic video as a completed vocal clip.
- Keep the memory-safe file pipeline, native resolution, bounded ffmpeg threads, and streaming Telegram delivery from PR #151.
- Do not run paid Suno/Kling requests during implementation or verification.

## Control case

For the 30-second elevator → corridor/street → orange Lamborghini Urus scenario:

1. `0–10`: phone goes into the pocket once; protagonist exits the elevator and proceeds through the corridor; camera begins front-facing and moves toward 3/4/profile.
2. `10–20`: continue from the previous physical state, exit to daylight, and approach the Urus; no reset to the elevator.
3. `20–30`: brunette remains in the front-right passenger seat with her bag/contents; protagonist enters through the left driver door and sits behind the wheel; roles, seats, and props do not swap or disappear.

The male rap begins only after the requested short instrumental intro. Lip-sync is applied only where the protagonist's face is visible and the vocal is active.

## Release gate

- Focused red-green tests for every changed contract.
- Full `python -m compileall -q .` and `PROD_HARDENING_ENABLED=0 python -m unittest discover -s tests -v` pass.
- GitHub required checks pass and review threads are clear before squash merge.
- Render auto-deploy reaches `LIVE` on the exact merged SHA; startup/webhook are healthy with no new `Traceback`, `server_failed`, or unexpected restart.

