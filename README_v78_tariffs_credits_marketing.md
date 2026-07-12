# v78 — тарифы + кредиты + безопасная экономика

Сборка поверх v77. Цель: не уходить в минус на видео/музыке/аватарах и одновременно сохранить понятные подписки.

## Что изменено

- Добавлена кредитная модель: 1 кредит ≈ 10 ₽ ≈ $0.10 при USD_RUB=100.
- FREE стал ознакомительным пакетом: GPT-лимит + 1 генерация картинки + 1 обработка фото в день.
- START / PRO / ULTIMATE теперь включают месячные кредиты.
- Тяжёлые функции списывают кредиты из единого баланса: Runway, Kling, Sora, Suno, AI-фото, FaceSwap, говорящий аватар, фото→видео, клип с вокалом.
- Обновлены цены тарифов:
  - START — 599 ₽ / $5.99, 20 кредитов/мес.
  - PRO — 1 990 ₽ / $19.90, 120 кредитов/мес.
  - ULTIMATE — 4 990 ₽ / $49.90, 350 кредитов/мес.
- Добавлены пакеты кредитов:
  - 100 кредитов — 990 ₽
  - 300 кредитов — 2 490 ₽
  - 700 кредитов — 4 990 ₽
- Баланс в интерфейсе теперь показывается как кредиты, а не как USD.
- При покупке подписки кредиты начисляются автоматически.
- WebApp `premium.html` обновлён под новые тарифы и кредиты.

## Что заменить в gpt5pro-bot

Переименовать и заменить:

```text
main_v78_tariffs_credits_marketing.py → main.py
requirements_v78_tariffs_credits.txt → requirements.txt
runtime_v78_tariffs_credits.txt → runtime.txt
render_v78_tariffs_credits.yaml → render.yaml
env_sample_v78_tariffs_credits.txt → env.sample
```

## Что заменить в gpt5pro-webapp

```text
premium_v78_tariffs_credits.html → webapp/premium.html
```

Рекомендуемая картинка WebApp:

```text
webapp/assets/hero.png
```

В HTML уже стоит:

```html
<img class="hero-image" src="assets/hero.png?v=78" ...>
```

Если хочешь использовать другое имя картинки, замени путь в `premium.html`.

## ENV, которые добавить/изменить

```env
PRICE_START_RUB=599
PRICE_PRO_RUB=1990
PRICE_ULT_RUB=4990
PRICE_START_USD=5.99
PRICE_PRO_USD=19.90
PRICE_ULT_USD=49.90
PRICE_START_QUARTER_RUB=1590
PRICE_PRO_QUARTER_RUB=5490
PRICE_ULT_QUARTER_RUB=13990
PRICE_START_YEAR_RUB=5990
PRICE_PRO_YEAR_RUB=19900
PRICE_ULT_YEAR_RUB=49900

USD_RUB=100
CREDIT_RUB_VALUE=10
CREDIT_USD_VALUE=0.10
START_INCLUDED_CREDITS=20
PRO_INCLUDED_CREDITS=120
ULT_INCLUDED_CREDITS=350

CREDIT_PACK_SMALL_CREDITS=100
CREDIT_PACK_SMALL_RUB=990
CREDIT_PACK_MID_CREDITS=300
CREDIT_PACK_MID_RUB=2490
CREDIT_PACK_BIG_CREDITS=700
CREDIT_PACK_BIG_RUB=4990

FREE_TEXT_PER_DAY=10
START_TEXT_PER_DAY=150
PRO_TEXT_PER_DAY=500
ULT_TEXT_PER_DAY=1500
FREE_IMAGE_GENERATIONS_PER_DAY=1
FREE_IMAGE_PROCESSINGS_PER_DAY=1

IMG_COST_USD=0.08
IMG_PROCESS_COST_USD=0.03
SUNO_COST_USD=0.20
SUNO_UNIT_COST_USD=0.20
AI_SELFIE_UNIT_COST_USD=0.15
FACESWAP_FAST_COST_USD=0.03
FACESWAP_PREMIUM_COST_USD=0.15
KLING_UNIT_COST_USD=0.60
RUNWAY_UNIT_COST_USD=0.60
SORA_UNIT_COST_USD=1.20
SORA_PRO_UNIT_COST_USD=1.80
AVATAR_UNIT_COST_USD=1.00
PHOTO_CLIP_UNIT_COST_USD=1.20
VOCAL_CLIP_UNIT_COST_USD=1.50
TEXT_VIDEO_UNIT_COST_USD=0.60
ONEOFF_MARKUP_DEFAULT=0.0
ONEOFF_MARKUP_RUNWAY=0.0

WEBAPP_URL=https://gpt5pro-webapp.onrender.com/premium.html?v=78
TARIFF_URL=https://gpt5pro-webapp.onrender.com/premium.html?v=78
```

## Проверка после деплоя

```text
/version
/plans
/balance
```

Ожидаемый `/version`:

```text
v78-tariffs-credits-marketing-2026-07-12
```

После оплаты подписки проверь, что появились кредиты:

```text
/balance
```

## Важная бизнес-логика

- GPT и базовые текстовые сценарии идут по лимитам тарифа.
- Тяжёлые генерации идут через кредиты.
- Если кредитов не хватает, бот предлагает купить пакет кредитов.
- Это защищает экономику от активных пользователей, которые массово запускают видео, музыку и аватары.
