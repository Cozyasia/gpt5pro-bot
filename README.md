# Neyro-Bot GPT 5 Studio — v119 Production Hardening

Version: `v119-production-hardening-2026-07-18`

## What changed

v119 adds a modular production layer in `neyrobot_prod/` without a dangerous one-shot rewrite of the 15k-line `main.py`.

- atomic, idempotent YooKassa, Telegram Payments and CryptoBot processing;
- server-side pre-checkout amount validation;
- SQLite WAL, busy timeout, foreign keys and transactional commercial tables;
- durable registry and startup recovery for provider task IDs;
- global and per-user limits for heavy generations;
- encrypted Medical Card backup together with the database;
- guaranteed Medical Card save/create prompt for PRO, ULTIMATE and unlimited users;
- guaranteed Medical Card PRO/ULTIMATE explanation for non-entitled users;
- one final official structured medical route instead of the v108/v111 startup race;
- production diagnostics and automated GitHub Actions tests;
- exact dependency versions for reproducible builds.

The old payment handlers remain in `main.py` only as inert compatibility code. v119 registers validated handlers in a higher-priority group and stops propagation, so the old duplicate paths cannot process the same Telegram payment.

## Automatic bootstrap

`sitecustomize.py` loads the production layer before `main.py`. No new secrets are required.

Recommended non-secret settings are listed in `PRODUCTION_ENV_V119.txt`. Defaults are already safe when those values are absent.

## Diagnostics

- `/version` — current release
- `/diag_prod` — SQLite, payment, queue, Medical Card and backup status
- `/diag_medcard` — entitlement, consent, pending save and active medical route
- `/diag_jobs` — unfinished durable provider jobs
- `/backup_now` — immediate owner-only backup

## Deploy

1. Merge the release into `main`.
2. Render: **Manual Deploy → Clear build cache & deploy**.
3. Run the checks in `VALIDATION.md`.

## Architecture direction

New critical behavior belongs in isolated modules. A later refactor can progressively move providers, billing and Telegram handlers out of `main.py`; v119 first removes the production risks while preserving the currently working user flows.
