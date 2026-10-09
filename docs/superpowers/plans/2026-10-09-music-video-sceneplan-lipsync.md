# Music-video ScenePlan and Post-process Lip-sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the reviewed music-video storyboard the exact immutable production contract, preserve cross-scene world state, and require Kling post-process lip-sync for vocal/face-visible intervals.

**Architecture:** Add a small pure `music_video_scene_plan.py` domain module with frozen scene/plan values, strict JSON validation, deterministic explicit-timeline fallback, and chunked review rendering. `main.py` owns the asynchronous GPT compiler adapter and transport orchestration, but stores and passes the compiled plan unchanged from draft approval through Kling scene prompts. Cinematic scenes remain file-backed; lip-sync extracts bounded scene/audio slices, invokes the Kling lip-sync endpoint, validates its MP4, and replaces only the selected interval.

**Tech Stack:** Python 3.12, `dataclasses`, existing `httpx` Comet/Kling transport, FFmpeg, python-telegram-bot, `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-09-music-video-sceneplan-lipsync.md`

## Global Constraints

- No paid Suno/Kling calls during implementation or verification.
- Existing Character Identity Pack, approval token, billing, saved-song, OOM-safety, and native-resolution behavior remain compatible.
- Original `SCENE_REFERENCE` is initial-scene context only.
- Vocal delivery fails closed when required lip-sync is absent or invalid.
- Production changes ship only through PR, green CI, squash merge, and Render auto-deploy.

## Review Focus

- Long Russian briefs without manual timecodes compile to complete, ordered scenes without silently losing tail content.
- A duration or text revision cannot approve or execute a stale ScenePlan.
- A continuation re-anchor cannot regain the elevator/reference composition after scene 1.
- Instrumental intros do not move lips; lip-sync fragments stay within provider 2–10 second limits.
- Provider/Telegram failures do not deliver a cinematic-only file under a vocal/lip-sync success label.

---

### Task 1: Immutable ScenePlan domain

**Files:**
- Create: `music_video_scene_plan.py`
- Create: `tests/test_music_video_scene_plan.py`

**Interfaces:**
- Produces: `SceneContract`, `ScenePlan`, `scene_plan_from_dict(payload, ...)`, `scene_plan_from_explicit_timeline(...)`, `render_scene_plan_review(plan, music_brief, video_brief)`, `chunk_review_messages(...)`.
- Consumes: only standard-library values and the specification.

- [ ] **Step 1: Write failing tests** for frozen values, strict ordered non-overlapping ranges, complete control-case states, explicit timestamp mapping, lip-sync interval bounds, and lossless review chunking.
- [ ] **Step 2: Run** `.venv/bin/python -m unittest tests.test_music_video_scene_plan -v`; expected failure because the module does not exist.
- [ ] **Step 3: Implement the pure domain module** with validation that rejects incomplete/mutated plans instead of repairing them silently.
- [ ] **Step 4: Run the focused tests**; expected all pass.
- [ ] **Step 5: Commit** the module, tests, spec, and plan.

### Task 2: One compiler and one approval contract

**Files:**
- Modify: `main.py` approval/compiler functions near `_music_video_director_plan`, `_stage_music_video_draft`, and `_on_music_video_draft_callback`
- Modify: `tests/test_music_video_approval.py`
- Modify: `tests/test_music_video_prompt_ux.py`

**Interfaces:**
- Consumes: Task 1 `ScenePlan` and render/chunk helpers.
- Produces: `async _compile_music_video_scene_plan(...) -> ScenePlan`, `_music_video_review_messages(...) -> list[str]`, and `draft["scene_plan"]` passed as `scene_plan=` to the selected provider pipeline.

- [ ] **Step 1: Write failing workflow tests** proving the long control prompt is not truncated, provider receives the same plan object/content that was reviewed, and every revision supersedes/recompiles the plan.
- [ ] **Step 2: Run the focused approval tests** and confirm the current truncation/reconstruction behavior fails them.
- [ ] **Step 3: Implement the strict JSON compiler adapter** with explicit-timeline deterministic handling and validated GPT JSON for prose briefs; send review chunks without `[:4096]` truncation and keep controls on the final chunk.
- [ ] **Step 4: Run approval and prompt UX tests**; expected all pass.
- [ ] **Step 5: Commit** the approval/compiler slice.

### Task 3: ScenePlan provider prompts and continuation-only re-anchor

**Files:**
- Modify: `main.py` scene prompt, vocal pipeline, and identity-keyframe functions
- Modify: `tests/test_music_video_world_state.py`
- Modify: `tests/test_music_video_identity_pack.py`
- Modify: `tests/test_music_video_stateful_director.py`
- Modify: `tests/test_music_video_resume_refs.py`

**Interfaces:**
- Consumes: approved `ScenePlan`.
- Produces: `_vocal_scene_role_prompt(..., scene_plan=...)` whose exact action/start/end/state comes from the reviewed scene, and `_run_comet_music_video_identity_keyframe(..., scene_reference: bytes | None, continuity_frame=...)` that omits `SCENE_REFERENCE` after scene 1.

- [ ] **Step 1: Write failing provider-boundary tests** for exact plan scene text and absence of `SCENE_REFERENCE` in continuation requests.
- [ ] **Step 2: Run focused world-state/identity tests** and verify expected failures.
- [ ] **Step 3: Thread the approved plan through `_start_vocal_clip`** and use continuation frame plus identity photos only after scene 1.
- [ ] **Step 4: Run focused tests**; expected all pass.
- [ ] **Step 5: Commit** the continuity slice.

### Task 4: Required file-safe post-process lip-sync

**Files:**
- Modify: `main.py` Kling configuration, transport, ffmpeg slice helpers, and high-fidelity vocal loop
- Create: `tests/test_music_video_lipsync.py`
- Modify: `tests/test_music_video_memory_safety.py`
- Modify: `env.sample`
- Modify: `render.yaml`

**Interfaces:**
- Consumes: `SceneContract.lip_sync_start_s` / `lip_sync_end_s`, cinematic scene file, and matching Suno audio.
- Produces: `_run_kling_lipsync_result_bytes(video_url, audio_url, ...)`, file-backed slice/replacement helpers, and a fail-closed scene path used by final concat.

- [ ] **Step 1: Write failing tests** for Kling `audio2video` payload/status paths, matching audio offsets, 2–10 second bounds, partial-scene prefix/suffix preservation, streaming file upload, and failure propagation.
- [ ] **Step 2: Run focused lip-sync/memory tests** and verify expected failures.
- [ ] **Step 3: Implement the post-process path**; require at least one plan interval for vocal clips and never fall back to unsynchronised delivery.
- [ ] **Step 4: Run focused tests and an offline FFmpeg smoke test** using generated color/sine fixtures; expected valid same-duration MP4 with no provider calls.
- [ ] **Step 5: Commit** the lip-sync slice.

### Task 5: Integrated verification and release

**Files:**
- Verify all changed files; no new production code unless a red test identifies a defect.

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: reviewed PR, squash merge, and verified Render deployment.

- [ ] **Step 1: Run** `.venv/bin/python -m compileall -q .` and `git diff --check`.
- [ ] **Step 2: Run** `env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy PROD_HARDENING_ENABLED=0 .venv/bin/python -m unittest discover -s tests -v`; expected zero failures/errors.
- [ ] **Step 3: Review the whole branch against the spec**, fix Critical/Important findings by red-green tests, and record deferred minors/rulings.
- [ ] **Step 4: Push the exact tested tree, open the PR, wait for all required GitHub checks, and ensure review threads are clear.
- [ ] **Step 5: Squash merge and verify Render auto-deploy**: exact SHA/deploy, `LIVE`, startup/webhook, no new `Traceback`/`server_failed`/unexpected restart, and memory below the 512 MiB limit.

