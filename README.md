# Neyro-Bot v91 — commercial pricing + Midjourney visibility

Version: `v91-commercial-pricing-midjourney-2026-07-13`

This release keeps all v90 features and fixes the commercial pricing layer.

## Main changes

- nominal `1 credit = 1 RUB` is locked by default;
- old Render values such as `CREDIT_RUB_VALUE=10` can no longer underprice every generation tenfold;
- provider costs use audited canonical values by default;
- minimum retail multiplier is `2.0`;
- all retail prices are rounded up to 5 credits;
- new `/prices` command;
- prices are available from the Engines and Balance menus;
- Midjourney is explicitly listed in the bot description, engine menu, mini-app and price list;
- OpenAI Images generation uses `medium` quality by default;
- credit-package discounts were reduced to protect margin.

## Retail prices in the default configuration

- OpenAI Images medium: 10 credits
- Midjourney Fast: 15 credits
- image processing: from 10 credits
- AI selfie: 30 credits
- Sora 2, 5 seconds: 100 credits
- Kling, 5 seconds: 50 credits
- Runway Gen-4.5, 5 seconds: 120 credits
- Suno: 40 credits
- talking avatar: 130 credits
- photo-to-music-video: 200 credits
- vocal clip / lip sync: 300 credits
- FaceSwap: 10 / 25 credits
- PDF + PPTX presentation render: 40 credits plus generated images

The final price is always shown before a paid job starts and is charged only after successful delivery.

## Pricing controls

Recommended Render variables:

```env
PRICING_CANONICAL_COSTS=1
PRICING_LOCK_1_CREDIT_1_RUB=1
PRICING_MIN_USD_RUB=100
PRICING_MIN_MULTIPLIER=2.0
CREDIT_RUB_VALUE=1
GENERATION_PRICE_MULTIPLIER=2.0
GENERATION_PRICE_ROUND_TO=5
```

With `PRICING_CANONICAL_COSTS=1`, stale cost variables in Render do not change the audited default costs. Set it to `0` only when intentionally managing every provider cost manually.

## Midjourney

Midjourney is integrated through CometAPI.

Required:

```env
COMET_API_KEY=...
MIDJOURNEY_ENABLED=1
MIDJOURNEY_MODE=fast
```

Direct command:

```text
/mj <prompt>
```

Natural text or voice requests for an image display the chooser: Auto / OpenAI Images / Midjourney.

## Runway secret

The existing Secret File setup remains supported. In `yookassa.env` or `runway.env`:

```env
RUNWAYML_API_SECRET=key_YOUR_RUNWAY_SECRET
```

## Deploy

1. Upload all release files to the repository root.
2. Keep `secret_loader.py`, `runway_official.py`, `presentation_studio.py` next to `main.py`.
3. Deploy with **Clear build cache & deploy**.
4. Run:

```text
/version
/prices
/diag_runway auth
```

Expected version:

```text
v91-commercial-pricing-midjourney-2026-07-13
```
