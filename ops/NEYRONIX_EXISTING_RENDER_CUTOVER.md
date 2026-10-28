# NEYRONIX cutover on existing paid Render service
Date: 2026-10-28
Production: gpt5pro-bot / srv-d3iofgp5pdvs7394e8rg / 1c-2g / /data (10 GB)
Target Telegram: @neyronixbot
Current production deploy: 85e8f0781f8b65c1767859bf5bc4d671330bbaf0 (live at audit)
DO NOT CUT OVER BEFORE BACKUP AND USER ACCEPTANCE TESTS.

1. Preserve the old bot token in Render secret management for rollback (never in repo or chat). Do not delete @progpt5_bot.
2. Obtain SQLite consistent backup of /data/subs.db, plus inventory of other files under /data. Validate restore and balances in a private environment. This has NOT been performed.
3. Verify how subscriptions, credits, transactions, referrals and payment callbacks are keyed. Telegram user IDs persist across bots; chat IDs and bot-specific Telegram features may not.
4. Verify local Telegram Bot API start script: /app/ops/start_telegram_local.sh calls cloud Bot API logOut on first run; ensure separate /data/telegram-api state per token. Existing .cloud_logout_completed marker must not be reused blindly with a new token.
5. Check WEBAPP_URL, BOT_USERNAME, BOT_PUBLIC_NAME, descriptions, BOT_MENU_TEXT, payment provider bindings, and webhook URLs. Do not switch a token without ensuring Telegram webhook registration and secret are correct.
6. Rehearse the cutover and rollback. Confirm user authorization for a short interruption. Do not change main branch as a preparation step.
7. Update only production Render BOT_TOKEN and BOT_USERNAME after a verified backup and approval, using secret settings. Restart/deploy deliberately; validate getMe, /start, menu, Mini App, credits, billing and logs. No credentials in logs.
8. Keep @progpt5_bot reachable with a migration notice if independently hosted; otherwise users will not be able to message it after cutover.
9. Leave staging service stopped or on a minimal probe. Its Free 512 MB RAM and no persistent disk are not suitable for the existing full bot.

Status: plan prepared; no backup, token change, or cutover executed.
