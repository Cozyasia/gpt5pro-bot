# NEYRONIX Migration Design

## Intent

Migrate the existing GPT5 Studio AI product to `@neyronixbot` without interrupting `@progpt5_bot`, while preserving server-side billing, user data integrity, provider behavior, and the established 3D Mini App design.

## Goals

- `@neyronixbot` identifies itself as NEYRONIX and exposes reliable `/start`, `/menu`, `/help`, Telegram commands, reply navigation, and a Mini App button.
- The Mini App routes every verified existing product entry to the current Telegram callback contract and never sends balances or privileged operations from JavaScript.
- Staging produces sanitized evidence for bot identity, webhook, menu, health, feature flags, and restart behavior.
- Marketplace drafts, billing, and provider execution are enabled only when the durable ledger and required secrets are present.
- Production data is backed up and migrated idempotently by Telegram user ID only after schema and balance reconciliation.
- The old bot remains online throughout the migration.

## Non-goals

- Moving Telegram chat history or bot-specific `file_id` values between bots.
- Renaming internal technical identifiers that are already stable integrations.
- Claiming an external AI provider works without a real API result.
- Changing tariffs or user balances as part of branding.

## Anti-goals

- Two consumers for one bot token.
- Shared writable SQLite between staging and production.
- Secrets in source, logs, test fixtures, or reports.
- A menu that advertises an unavailable route as working.

## Constraints

- Migration work remains on `work/neyronix-migration-20261028` until staging acceptance.
- `main` and `srv-d3iofgp5pdvs7394e8rg` remain unchanged during staging.
- The 1.1 MB legacy `main.py` is modified at image build time through a reviewed patch because the connected GitHub writer has a single-blob limit.
- Existing handler behavior and callback payloads are reused; the Mini App only performs a safe handoff to Telegram.
- Protected operations continue in the bot/server. Mini App navigation itself carries no trusted user or balance data.

## Approaches considered

1. Replace `main.py` wholesale. Rejected because of connector size limits and high regression risk in a monolithic production file.
2. Add a second independent NEYRONIX application. Rejected because it duplicates billing/data/provider logic and creates divergence.
3. Keep the production runtime and add a small NEYRONIX overlay plus verified build patch. Selected because it preserves existing behavior, is reversible, and can be tested independently.

## Selected design

Add focused NEYRONIX modules for branding, Telegram commands/menu configuration, sanitized startup diagnostics, and Mini App route contracts. Apply the minimal `main.py` integration delta during Docker build. Copy the deployed static UI baseline into the migration branch, rebrand it, point all deep links at `neyronixbot`, and expose only callbacks verified in the current application handler graph. Deploy to the existing staging service, verify with Render logs and health endpoints, and then perform a separately validated data backup/migration step before any production cutover.

## Acceptance evidence

- Automated red/green tests for brand text, `/menu`, bot commands, default and per-chat menu URL, callback allowlist, Mini App bot username, and startup diagnostics.
- Full repository test result with pre-existing failures explicitly separated from migration regressions.
- Render deploy ID, live health check, sanitized `getMe` username, webhook URL, menu URL, restart evidence, and absence of new critical errors.
- SQLite integrity checks, table counts, payment IDs, balance totals, and backup checksum before data migration.
- Real provider checks classified individually as passed, failed, or not tested.
