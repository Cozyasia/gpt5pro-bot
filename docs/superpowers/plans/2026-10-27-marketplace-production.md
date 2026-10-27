# Marketplace Product Cards Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship reference-grounded marketplace product images in the existing Telegram bot with voice briefs, truthful quotes, durable idempotent billing, recovery, CI, and Render production deployment.

**Architecture:** Keep the existing wizard and Telegram routing, but replace the provisional wallet-debit adapter with a production ledger that uses the existing `wallet.usd` and `credit_ledger` reservation semantics. Generate a declared shot plan with the current OpenAI image-edit model, persist outputs under `/data`, deliver documents in order, and charge exactly once only after confirmed delivery; restart recovery reuses saved files without repeating provider calls.

**Tech Stack:** Python 3.12, python-telegram-bot 21.6, OpenAI Images API, SQLite/WAL, Pillow, unittest/pytest, GitHub Actions, Render Docker service.

**Spec:** `docs/BUSINESS_MARKETPLACE_STUDIO_SPEC.md`

## Global Constraints

- Use the existing bot, production branch, SQLite database, `/data` disk, pricing multiplier, and shared USD-backed credit wallet.
- No production balance mutation in tests; all financial tests use temporary SQLite databases.
- Never retry a paid provider request automatically or repeat it after a callback/restart.
- Do not claim video support when only still-image generation is implemented.
- Preserve reference order, product appearance, Russian UI/copy, and all existing property/video routes.
- Do not log API keys, tokens, user audio, or raw user images.

## Review Focus

- Duplicate callbacks and process restarts must not create a second provider call or charge.
- Provider success followed by Telegram delivery failure must leave recoverable files and an uncharged reservation.
- Quotes must become invalid after any output, marketplace, reference, or brief change.
- More than the provider reference limit must use a deterministic disclosed primary selection without rejecting the whole project.
- Partial multi-image delivery must not charge until every expected file is confirmed delivered.

---

### Task 1: Production quote and runtime bootstrap

**Files:**
- Modify: `neyrobot_prod/marketplace_runtime.py`
- Create: `neyrobot_prod/marketplace_pricing.py`
- Modify: `main.py`
- Test: `tests/test_marketplace_runtime.py`
- Test: `tests/test_marketplace_pricing.py`

**Interfaces:**
- Produces: `MarketplaceQuote`, `build_marketplace_quote_service(...)`, and `configure_marketplace_runtime(...)` with injected ledger, quote service, provider client, model and artifact directory.

- [x] Write failing tests for the current model, itemized quote, existing pricing multiplier, fail-closed startup, and the existing CI `api_key` failure.
- [x] Run the focused tests and confirm failure.
- [x] Implement the quote service and runtime bootstrap using `DB_PATH`, `_retail_usd`, `_usd_to_credits`, `OPENAI_API_KEY`, and `/data/marketplace_jobs`.
- [x] Run focused tests and confirm pass.

### Task 2: Existing-ledger-compatible durable billing

**Files:**
- Replace: `neyrobot_prod/marketplace_usd_ledger.py`
- Test: `tests/test_marketplace_usd_ledger.py`
- Test: `tests/test_marketplace_billing_recovery.py`

**Interfaces:**
- Produces: `reserve`, `mark_provider_started`, `record_output`, `mark_delivery_unknown`, `commit`, `release`, `status`, and `recoverable_jobs` on `SQLiteUSDWalletLedger`.

- [x] Write failing tests for capacity reservation without early debit, exact-once delivery debit, duplicate/collision handling, pre-provider release, post-provider retention, saved outputs, and restart recovery.
- [x] Run the focused tests and confirm failure.
- [x] Implement transactions against `wallet.usd` and `credit_ledger`, plus durable marketplace job/output tables.
- [x] Run focused tests and confirm pass.

### Task 3: Grounded multi-output provider and reference selection

**Files:**
- Modify: `neyrobot_prod/marketplace_generation.py`
- Modify: `neyrobot_prod/marketplace_image_provider.py`
- Create: `neyrobot_prod/marketplace_infographic.py`
- Modify: `neyrobot_prod/marketplace_pipeline.py`
- Test: `tests/test_marketplace_generation.py`
- Test: `tests/test_marketplace_image_provider.py`
- Test: `tests/test_marketplace_pipeline.py`

**Interfaces:**
- Consumes: `MarketplaceQuote` and durable ledger operations.
- Produces: ordered `ShotSpec` values, deterministic primary-reference selection, Russian infographic composition, and saved output artifacts.

- [x] Write failing tests for photo, infographic and complete-package shot counts; 30-reference deterministic selection; current model parameters; Cyrillic overlay; and partial-delivery recovery.
- [x] Run the focused tests and confirm failure.
- [x] Implement shot planning, current OpenAI image edit calls, local Cyrillic text rendering, durable files, ordered document delivery, and exact-once commit.
- [x] Run focused tests and confirm pass.

### Task 4: Telegram workflow, voice correction and truthful UI

**Files:**
- Modify: `neyrobot_prod/marketplace_studio.py`
- Modify: `neyrobot_prod/marketplace_navigation.py`
- Modify: `neyrobot_prod/marketplace_telegram.py`
- Modify: `neyrobot_prod/marketplace_telegram_media.py`
- Modify: `neyrobot_prod/entertainment/production.py`
- Modify: `main.py`
- Test: `tests/test_marketplace_integration.py`
- Test: `tests/test_marketplace_generate_callback.py`
- Test: `tests/test_marketplace_transcript.py`

**Interfaces:**
- Consumes: quote, provider, ledger, and pipeline services from `bot_data`.
- Produces: voice/text brief review, editable back flow, disclosed selected references, itemized count/cost/charge, and one guarded generation callback.

- [x] Write failing tests for voice transcript display/edit, 30-photo intake, quote details, unsupported video disclosure, callback locking, and old-route non-interception.
- [x] Run the focused tests and confirm failure.
- [x] Implement the Telegram state/UI changes and startup recovery hook without changing unrelated handlers.
- [x] Run focused tests and confirm pass.

### Task 5: Full verification, merge and deployment

**Files:**
- Modify only defects found by verification.

**Interfaces:**
- Produces: mergeable PR, passing CI, live Render deploy, healthy startup logs, and a prepared owner E2E Telegram script.

- [x] Run Python compilation, focused tests, full production test suite, and static secret/log checks.
- [ ] Rebase/merge current `main` into the feature branch and rerun verification.
- [ ] Push the feature branch, wait for all GitHub Actions, mark PR ready, and merge PR #219 with a rollback SHA recorded.
- [ ] Wait for the automatic Render deploy, inspect build/runtime logs and service health, and verify runtime initialization without exposing secrets.
- [ ] Execute a no-charge isolated financial recovery test and request only the final owner Telegram action if a live provider/Telegram E2E cannot be initiated safely without user interaction.
