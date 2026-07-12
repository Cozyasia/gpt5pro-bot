# v81 — YooKassa API ready + Secret Files + diagnostics

## Что изменено

- Бот читает API-ключи ЮKassa из Render Secret File `/etc/secrets/yookassa.env`.
- Добавлена команда `/diag_yookassa` для безопасной проверки настроек без показа секретов.
- В тарифах убрана фраза про внутреннюю экономику; теперь текст: все платные тарифы открывают функции, разница в кредитах/лимитах/очереди.
- Добавлена универсальная кнопка `🌐 Все способы ЮKassa`: платёж создаётся без жёсткого метода, форма ЮKassa показывает доступные способы магазина.
- Сохраняются отдельные кнопки: `⚡ СБП / QR`, `🟢 SberPay`, `🟡 T-Pay`, `💙 Mir Pay`, `💳 Карта Telegram`, `💠 CryptoBot`.

## Secret File в Render

Файл должен называться строго:

```text
yookassa.env
```

Содержимое:

```env
YK_ID=1185809
YK_KEY=ВАШ_SECRET_KEY_API_ЮKASSA
```

`YK_KEY` — это секретный ключ API ЮKassa из раздела `Ключи API`, не mSDK и не Telegram provider token.

## Важно про PROVIDER_TOKEN_YOOKASSA

`PROVIDER_TOKEN_YOOKASSA` — это отдельный токен для Telegram Payments. Он должен выглядеть примерно как `390540012:LIVE:...`.

Не вставляйте туда `live_...` secret key от API ЮKassa. API secret должен быть только в `yookassa.env` как `YK_KEY`.

## Проверка

После деплоя в боте:

```text
/version
/diag_yookassa
/plans
```

Ожидаемая версия:

```text
v81-yookassa-api-ready-2026-07-12
```

Если `/diag_yookassa` показывает `Direct API ЮKassa настроен`, можно тестировать `⚡ СБП / QR`.
