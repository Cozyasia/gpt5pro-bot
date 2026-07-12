# Neyro-Bot v82 — YooKassa payment diagnostics/fix

Версия: `v82-yookassa-payment-debug-2026-07-12`

Что изменено:

1. SberPay переведен на `confirmation.type=redirect` вместо `external`.
2. Добавлена подробная диагностика ошибки ЮKassa при создании платежа.
3. Добавлена поддержка `receipt` для магазинов с онлайн-кассой/чеками через Secret File.
4. `/diag_yookassa` теперь показывает, видит ли бот receipt email и VAT code.

## Secret File

Render → Environment → Secret Files → `yookassa.env`:

```env
YK_ID=1185809
YK_KEY=ВАШ_СЕКРЕТНЫЙ_API_KEY_ЮКАССА
YK_RECEIPT_EMAIL=ваш_email_для_чеков@example.com
YK_VAT_CODE=1
```

`YK_RECEIPT_EMAIL` нужен, если ЮKassa возвращает ошибку по чеку/receipt.

## Проверка

В боте:

```text
/version
/diag_yookassa
/plans
```

Сначала тестируйте кнопку `🌐 Все способы ЮKassa`, затем `⚡ СБП / QR`.
