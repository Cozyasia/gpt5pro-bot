# Neyro-Bot GPT 5 Studio — v79 tariffs + YooKassa payments

Версия: `v79-tariffs-payment-methods-2026-07-12`

## Что изменено

- Тарифы переписаны без ощущения закрытых функций: все платные тарифы открывают AI-функции, разница в кредитах, лимитах GPT, скорости очереди и объёме генераций.
- В тарифный экран добавлено объяснение кредитов: тяжёлые генерации списывают кредиты только при успешном результате.
- В оплату тарифов добавлены отдельные способы:
  - ⚡ СБП / QR
  - 🟢 SberPay
  - 🟡 T-Pay / Tinkoff Pay
  - 💙 Mir Pay
  - 💳 Карта
  - 💠 CryptoBot
  - 🧾 С баланса
- СБП/SberPay/T-Pay/Mir Pay создаются через прямой API ЮKassa `/v3/payments`, бот отправляет пользователю ссылку и сам ждёт статус оплаты polling-ом.

## Замена файлов в gpt5pro-bot

```text
main_v79_tariffs_payments_yookassa.py → main.py
requirements_v79_tariffs_payments.txt → requirements.txt
runtime_v79_tariffs_payments.txt → runtime.txt
render_v79_tariffs_payments.yaml → render.yaml
```

## Замена файла в gpt5pro-webapp

```text
premium_v79_tariffs_payments.html → webapp/premium.html
```

## Новые ENV

```env
YOO_DIRECT_ENABLED=1
YOO_SHOP_ID=...
YOO_SECRET_KEY=...
YOO_PAYMENT_RETURN_URL=https://gpt5pro-bot.onrender.com/payment_return
YOO_DEFAULT_METHOD=sbp
YOO_SBP_ENABLED=1
YOO_SBERPAY_ENABLED=1
YOO_TPAY_ENABLED=1
YOO_MIRPAY_ENABLED=1
YOO_CARD_ENABLED=1
YOO_PAYMENT_POLL_SECONDS=900
YOO_PAYMENT_POLL_INTERVAL_S=5
WEBAPP_URL=https://gpt5pro-webapp.onrender.com/premium.html?v=79
TARIFF_URL=https://gpt5pro-webapp.onrender.com/premium.html?v=79
```

`YOO_SHOP_ID` — Shop ID магазина ЮKassa.  
`YOO_SECRET_KEY` — секретный ключ API из кабинета ЮKassa.

## Проверка

```text
/version
/plans
```

Ожидаемая версия:

```text
v79-tariffs-payment-methods-2026-07-12
```

Проверить оплату можно с тестовой подпиской START: нажать `/plans` → START → ⚡ СБП / QR.
