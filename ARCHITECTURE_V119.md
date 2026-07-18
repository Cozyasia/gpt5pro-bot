# Architecture plan after v119

v119 deliberately avoids replacing the entire monolith in one deploy. It creates stable seams first:

- `neyrobot_prod/db.py` — SQLite policy, production schema and backups
- `neyrobot_prod/payments.py` — one transactional payment processor
- `neyrobot_prod/jobs.py` — durable provider task registry/recovery
- `neyrobot_prod/limits.py` — heavy-work concurrency control
- `neyrobot_prod/medical_followup.py` — one official medical route and Medical Card hand-off
- `neyrobot_prod/bootstrap.py` — priority handlers, diagnostics and startup lifecycle

## Next extraction sequence

1. Move payment creation/UI into `services/payments/`; delete inert legacy payment code only after one stable release.
2. Move provider clients and task pollers into `services/providers/`.
3. Move Medical Engine/Card into `features/medical/` without runtime monkey-patching.
4. Move Presentation Studio into `features/presentation/` and remove the old direct PPTX/PDF generators.
5. Split Telegram routing into explicit handler modules.
6. Replace SQLite with PostgreSQL only when real concurrent load requires it; keep SQLite backups for export/migration.

Each extraction should preserve the v119 tests and add feature-specific integration tests before deleting the old implementation.
