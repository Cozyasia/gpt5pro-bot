# Neyro-Bot v94 — Telegram menu checkout fix

Version: `v94-menu-checkout-fix-2026-07-14`

## Why v93 could stay silent
The bottom Telegram **Меню ботов** button may still have been configured by BotFather with an old plain `premium.html` URL. That URL did not contain the signed server checkout endpoint. The page therefore used the old `sendData()` fallback, closed the Mini App, and no payment request reached the bot.

## Fixes in v94

- the bot automatically updates the default Telegram menu button through `setChatMenuButton` on every deploy;
- the menu URL now includes the current `/webapp/checkout` endpoint and cache-buster;
- the current project has a safe checkout URL fallback in `premium.html`;
- the page no longer silently closes when the server bridge is unavailable;
- a bot deep-link fallback creates the invoice in chat;
- `/webapp/checkout` supports GET/HEAD/OPTIONS for diagnostics;
- `/` and `/healthz` return successful responses, removing the harmless `HEAD / 404` warning.

## Deploy

Upload all files and run:

`Manual Deploy → Clear build cache & deploy`

No new secrets are required.

Recommended environment variables:

```env
AUTO_SET_BOT_MENU=1
BOT_MENU_TEXT=Меню ботов
```

## Check

1. `/version` → `v94-menu-checkout-fix-2026-07-14`
2. Open `https://gpt5pro-bot.onrender.com/webapp/checkout` — JSON with `ok: true` is expected.
3. Close and reopen the Telegram chat so the updated menu button is refreshed.
4. Open **Меню ботов** and press a tariff/package.
5. Expected: YooKassa opens and a payment button also appears in the bot chat.
