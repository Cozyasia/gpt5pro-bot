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
- New bot token not provisioned in a separate Render staging service.
- No separate staging service yet; cannot safely test webhook or API.
- Production persistent disk cannot be assumed safely shareable.
- Domain neyronix.ai is not purchased or configured.

## Verified follow-up — 2026-10-28 19:08 UTC
- Production deploy `dep-dbh3lh61egvs739cghag` is live.
- Render Web Shell showed `DB_PATH=/data/subs.db`, 29 tables, `PRAGMA integrity_check=ok`, and active process PID 26 with open `/data/subs.db`, `-wal`, `-shm` file descriptors.
- SQLite online backup `/data/neyronix-backups/pre-neyronix-20261028T190839Z.sqlite3` created successfully; integrity `ok`, 29 tables. Counts: `ai_chats=1`, `ai_chat_active=1`, `production_events=2`, `processed_telegram_events=5`, `processed_start_messages=4`.
- Existing backup is on the same persistent disk: export an off-host encrypted copy before destructive operations. No token switch or production redeploy authorized by this verification.
