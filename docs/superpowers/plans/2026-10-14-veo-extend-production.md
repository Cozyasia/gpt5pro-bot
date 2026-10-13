# Veo 3.1 Extend Production Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing Veo integration use only a verified native-extension contract, preserve paid-task recovery, and deploy the smallest safe production fix.

**Architecture:** Keep the existing durable job pipeline and Telegram entry points. Add a provider contract boundary that distinguishes CometAPI's documented `/v1/videos` generation API from its non-contractual chat preview example; route native extension through an explicitly supported provider only, otherwise stop before a paid request with a recoverable state.

**Tech Stack:** Python 3.12, httpx, unittest, GitHub, Render, FFmpeg.

**Spec:** User request in the active conversation.

## Global Constraints

- Do not regenerate the already-paid initial 8-second task.
- Never automatically retry an ambiguous paid POST.
- Native extension must consume the provider's prior Veo video object/URI.
- Preserve existing Telegram and non-Veo flows.
- Do not claim real Extend success without a paid-provider result.

## Review Focus

- Comet model spelling differs between `/v1/videos` (`veo3.1`) and chat preview examples (`veo-3.1`): request builder test.
- HTTP 503 model/channel refusal must not be marked as an unknown paid outcome: error-classification test.
- Accepted extension without a result URI must remain recoverable without resubmission: journal test.
- Existing completed initial task must be reused: recovery test.
- Durations beyond the provider contract must fail before any POST: limit test.

### Task 1: Verify provider contract and characterize current failure

- [x] Inspect current code, production logs, commit `1aa3ae4`, and official CometAPI/Google documentation.
- [x] Confirm the current request is `/v1/chat/completions` with model `veo-3.1`, while CometAPI's current API reference documents `/v1/videos` with `veo3.1`/`veo3.1-fast` for generation and does not document a native Extend endpoint.

### Task 2: Add no-charge regression coverage

- [ ] Test payload/model routing and provider-error classification.
- [ ] Test journal states for confirmed refusal, uncertain transport, and accepted-without-result responses.
- [ ] Test the existing completed scene is reused and duration validation remains bounded.

### Task 3: Implement the smallest safe provider boundary

- [ ] Stop calling the undocumented Comet chat route as if it were guaranteed native Extend.
- [ ] Preserve the initial generation and provider task recovery path.
- [ ] Keep an explicit extension adapter seam for a provider with a verified native contract, with no automatic paid retry.

### Task 4: Verify, commit, deploy, and inspect production

- [ ] Run syntax, focused Veo tests, and the full test suite.
- [ ] Commit and push to `main`.
- [ ] Confirm Render deploy reaches `LIVE` and startup logs are clean.
- [ ] Report real Extend as unverified until a paid call is authorized and returns a native cumulative video.
