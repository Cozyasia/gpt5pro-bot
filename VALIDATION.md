# VALIDATION — v94

## Version
`/version` must show:

`v94-menu-checkout-fix-2026-07-14`

## Server route
Open:

`https://gpt5pro-bot.onrender.com/webapp/checkout`

Expected JSON contains:

`{"ok": true, ...}`

## Telegram menu
After deploy, fully close and reopen the bot chat. The system menu button is set automatically to the v94 URL.

## Payment test
Press START/PRO/ULTIMATE or a credit package.

Expected:

- payment status appears in the Mini App;
- YooKassa opens;
- the bot chat receives a message with a payment button.

If the server bridge fails, the Mini App opens the bot using a `pay_sub_*` or `pay_pack_*` deep link instead of closing silently.
