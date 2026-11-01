# NEYRONIX bot migration runbook (staging only)

Source: Cozyasia/gpt5pro-bot main. Target: @neyronixbot. Do not replace the production bot token or deploy this branch to production before acceptance.

## Verified infrastructure (2026-10-28)
- Production Render service gpt5pro-bot (srv-d3iofgp5pdvs7394e8rg), branch main, Docker, persistent /data 10 GB, Singapore.
- Main repository render.yaml declares BOT_TOKEN, BOT_USERNAME, WEBAPP_URL, PUBLIC_URL, USE_WEBHOOK, WEBHOOK_PATH=/tg, TELEGRAM_WEBHOOK_SECRET, DB_PATH=/data/subs.db, AUTO_SET_BOT_PROFILE, AUTO_SET_BOT_MENU.
- Static UI service neyro-studio-ui (srv-dbgivkc9v7es738nf0lg) deploys studio-static-menu; separate from production bot.
- Bot created as @neyronixbot. Bot API token must never be committed, pasted in chat or shared in logs.

## Migration safeguards
1. Take a verified, restorable backup of production /data/subs.db (SQLite consistent backup, not naive copy during writes), and inventory other persisted files, user credits, subscriptions, jobs and payment IDs.
2. Build a separate staging service from this branch, with separate bot token, distinct PUBLIC_URL and webhook secret. Do not mount production disk or share its writable DB. Restrict staging access to owner/admin IDs; disable paid operations until billing checks pass.
3. Provide NEYRONIX BOT_TOKEN directly in Render secret environment settings; do not copy old BOT_TOKEN. Set BOT_USERNAME=neyronixbot. Set WEBAPP_URL to approved Mini App URL after verifying Telegram initData handling and server-side auth.
4. Review bot-specific identifiers and deep links, payment provider settings, webhook registration and callback URLs. Never allow both services to poll or set webhook for the same bot token.
5. Run tests: /start, menu, Mini App load, initData auth, AI chat, image, video, music, product cards, billing, user isolation, persistence and error handling. Record evidence and failures.
6. Plan explicit data migration keyed by Telegram user ID; verify schema and balances first. Do not copy raw production DB to public staging.
7. Cut over only after user approval; keep @progpt5_bot online with migration notice. Telegram cannot automatically move chat history or subscribers.

## Current blockers
- The staging service has no persistent disk and therefore cannot be the source
  of truth for subscriptions, credits, payments, or long-running jobs.
- A fresh, off-host, encrypted production backup and a restore rehearsal are
  still required before any data cutover.
- Paid provider end-to-end calls have not yet been authorized against a bounded
  test budget; provider names in the menu are not treated as proof of service.
- Domain neyronix.ai is not purchased or configured; the verified Render URLs
  remain the active endpoints.

## Verified follow-up — 2026-10-28 19:08 UTC
- Production deploy `dep-dbh3lh61egvs739cghag` is live.
- Render Web Shell showed `DB_PATH=/data/subs.db`, 29 tables, `PRAGMA integrity_check=ok`, and active process PID 26 with open `/data/subs.db`, `-wal`, `-shm` file descriptors.
- SQLite online backup `/data/neyronix-backups/pre-neyronix-20261028T190839Z.sqlite3` created successfully; integrity `ok`, 29 tables. Counts: `ai_chats=1`, `ai_chat_active=1`, `production_events=2`, `processed_telegram_events=5`, `processed_start_messages=4`.
- Existing backup is on the same persistent disk: export an off-host encrypted copy before destructive operations. No token switch or production redeploy authorized by this verification.

## Verified staging restoration — 2026-11-01 08:31 UTC

- GitHub migration branch `work/neyronix-migration-20261028` advanced from
  `9a66c7ac` to connector commit `79aaa41b`; `main` was not changed.
- Backend service `neyronix-bot-staging` (`srv-dbh2rdt9fdbs73a3i3d0`)
  deployed `79aaa41b` as `dep-dbjffi49v7es739uvuj0`, terminal status `live`.
- `/healthz` returned HTTP 200. Sanitized startup verification reported
  username `neyronixbot`, first name `NEYRONIX`, zero pending updates, no
  webhook error, webhook `https://neyronix-bot-staging.onrender.com/tg`, eight
  public commands, and Mini App menu URL
  `https://neyro-studio-ui.onrender.com/`.
- Telegram `Application started` after the verification gate. No traceback was
  present in the post-deploy log window.
- Static Mini App branch `studio-static-menu` advanced to `f719e91f`; a clean
  rebuild `dep-dbjfgm2jnfac73frh7pg` reached `live`. The served HTML checksum
  matched the repository file after CDN invalidation.
- Browser verification found the NEYRONIX brand, 11 catalog cards, 11 available
  routes, no horizontal overflow, a 64 px bottom navigation, and an enabled
  Telegram launch action for the AI-Medicine card.
- Focused shell/navigation tests passed: 39 tests plus 21 subtests. The full
  suite completed with 736 passed, 17 failed, and 89 subtests passed; one of
  the 17 failures is an order-dependent celebrity-selfie state leak that passes
  alone, while the other 16 reproduce the pre-migration baseline failures.
- Old production service `srv-d3iofgp5pdvs7394e8rg` remained on deploy
  `dep-dbh3lh61egvs739cghag`; neither its branch, token, nor disk was changed.
