# Telegram Bot API local mode (up to 2 GB uploads)

This is an **opt-in deployment**. Merely committing these files does not change the existing Render Python service.

## Existing deployment
- Webhook: `PUBLIC_URL/tg`
- Render public port: `PORT` (Python web server)
- Persistent disk: `/data` (10 GB currently provisioned)
- Local Bot API listens only at `127.0.0.1:8081`, not publicly.

## Before switching the Render runtime
1. Confirm `MT_API_ID` and `MT_API_HASH` are set in **gpt5pro-bot** Render environment (secret values, never in Git).
2. Keep `BOT_TOKEN`, `PUBLIC_URL`, `TELEGRAM_WEBHOOK_SECRET` unchanged.
3. Check disk free space and RAM; 300 MB video may need >600 MB free temporary space.
4. Switch service runtime to Docker using `Dockerfile.telegram-local` as the Dockerfile path and preserve the existing disk and environment variables.
5. Before first local Bot API usage, call official cloud Bot API `logOut` for the bot token. This can cause a brief outage and should be performed only in a coordinated maintenance window.
6. Confirm webhook re-registration succeeds, then send a small test message, 60 MB test file, then 300 MB test file.

**Important:** The local Bot API server and Python bot MUST share the same filesystem for `local_mode(True)` path uploads. This Docker image runs both processes in one container. The public webhook stays on the Python service.

**Rollback:** Restore the Python runtime/start command, remove `TELEGRAM_LOCAL_API_URL`, and re-register the webhook through the cloud API. Be aware Telegram may enforce a temporary delay before cloud login after local logout.

Do not enable this image until credentials, migration timing and resource checks are complete.
