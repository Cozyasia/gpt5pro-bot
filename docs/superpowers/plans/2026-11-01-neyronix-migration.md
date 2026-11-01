# NEYRONIX Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a verified NEYRONIX staging deployment that preserves the existing bot and is ready for a separately validated production data cutover.

**Architecture:** Keep the existing production runtime and introduce a small NEYRONIX overlay plus a build-time integration patch. The Mini App uses verified Telegram deep-link handoffs; billing and identity remain server-side.

**Tech Stack:** Python 3.12, python-telegram-bot 21.6, SQLite, static HTML/JavaScript Mini App, Docker, Render, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-01-neyronix-migration-design.md`

## Global Constraints

- Do not modify or redeploy the old production service during staging.
- Do not expose or replace secrets.
- Do not share a writable SQLite database between services.
- Use TDD for every behavior change and verify each integration with fresh evidence.
- Classify untested provider behavior as unverified.

## Review Focus

- New and existing chats must both receive a usable Telegram menu.
- A cold Render start must not lose or duplicate `/start` handling.
- Deep links must target `neyronixbot` and only allow verified slugs.
- Duplicate updates and payment callbacks must remain idempotent.
- Missing provider credentials must fail closed without charging credits.

---

### Task 1: NEYRONIX Telegram shell

**Files:**
- Create: `neyrobot_prod/neyronix_telegram.py`
- Create: `tests/test_neyronix_telegram.py`
- Create: `ops/main_neyronix.patch`
- Modify: `Dockerfile`

**Interfaces:**
- Produces: brand constants, menu URL resolver, `/menu` response helpers, bot command list, and sanitized post-init verification.

- [ ] Write failing tests for NEYRONIX brand, `neyronixbot`, command list, and Mini App menu URL.
- [ ] Run focused tests and confirm the expected failures.
- [ ] Implement the overlay and minimal build patch.
- [ ] Run focused tests, patch-application test, and affected Telegram tests.
- [ ] Commit the slice.

### Task 2: Full verified Mini App navigation

**Files:**
- Modify: `neyrobot_prod/studio_menu_catalog.py`
- Modify: `neyrobot_prod/studio_menu_navigation.py`
- Modify: `neyrobot_prod/studio_menu_dispatch.py`
- Replace from deployed baseline and modify: `web/studio_menu.html`
- Test: `tests/test_studio_menu_*.py`

**Interfaces:**
- Consumes: existing callback payloads from `main.py` and production modules.
- Produces: strict slug-to-callback mapping for all verified cards.

- [ ] Write failing tests for every verified route and for rejected arbitrary callback payloads.
- [ ] Run tests and confirm failures.
- [ ] Implement the allowlist and NEYRONIX UI/deep links.
- [ ] Run contract tests and static HTML assertions.
- [ ] Commit the slice.

### Task 3: Staging configuration and deploy

**Files:**
- Modify: `ops/NEYRONIX_MIGRATION.md`
- Modify: staging Render environment (non-secret values only).

**Interfaces:**
- Consumes: Tasks 1–2 and existing Render secrets.
- Produces: one staging deployment with sanitized runtime evidence.

- [ ] Push the migration branch without touching `main`.
- [ ] Set NEYRONIX brand, username, public URL, Mini App URL, webhook mode, and safe feature flags.
- [ ] Trigger staging deploy and wait for a terminal state.
- [ ] Verify health, `getMe`, webhook, commands, menu, restart, and logs.
- [ ] Commit evidence/runbook updates.

### Task 4: Data backup and idempotent migration rehearsal

**Files:**
- Create or modify: `ops/backup_subs_db.py`
- Create: `ops/reconcile_neyronix_db.py`
- Test: `tests/test_neyronix_data_migration.py`

**Interfaces:**
- Produces: consistent backup, checksums, schema inventory, and read-only reconciliation report.

- [ ] Write failing tests for repeatable migration and payment/balance preservation.
- [ ] Implement consistent backup and idempotent copy keyed by Telegram user ID.
- [ ] Verify integrity and restore on a private copy.
- [ ] Record counts and balance reconciliation; do not cut over on mismatch.
- [ ] Commit the slice.

### Task 5: Provider and billing verification

**Files:**
- Create: `ops/neyronix_capability_audit.py`
- Create: `tests/test_neyronix_capability_audit.py`

**Interfaces:**
- Produces: machine-readable feature/provider/billing matrix and bounded real-test runner.

- [ ] Inventory commands, callbacks, providers, required env keys, and pricing hooks.
- [ ] Run mock failure/retry/refund tests.
- [ ] Run one bounded real call for each authorized provider with available credentials.
- [ ] Record passed, failed, and unverified capabilities without inference.
- [ ] Commit the slice.

### Task 6: Production readiness and rollback gate

**Files:**
- Modify: `ops/NEYRONIX_EXISTING_RENDER_CUTOVER.md`

**Interfaces:**
- Consumes: all prior evidence.
- Produces: explicit go/no-go report and tested rollback instructions.

- [ ] Run the full test suite and classify all failures.
- [ ] Recheck old production health and staging metrics/errors.
- [ ] Verify backup restore and rollback prerequisites.
- [ ] Perform production transition only when all critical gates pass and the user-authorized risk boundary is satisfied.
- [ ] Produce the final evidence table.
