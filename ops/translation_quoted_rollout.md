# Quoted translated lip sync: rollout notes

The existing route remains active while `TRANSLATION_QUOTED_FLOW_ENABLED` is unset or false. The new route is limited to one 2–10 second segment and offers Russian, English, Thai, and Spanish.

Before enabling, independently verify the active provider, model and billing terms and set positive USD estimates for a maximum-length supported job: `TRANSLATION_IDENTIFY_USD`, `TRANSLATION_LIPSYNC_USD`, `TRANSLATION_STT_USD`, `TRANSLATION_TEXT_USD`, and `TRANSLATION_TTS_USD`. The language and speech values are job totals, not per-token or per-second rates. These are estimates, not proof of the provider's actual debit. The application's existing retail conversion computes the fixed customer quote.

Quotes expire after 15 minutes and are lost on restart before confirmation; users may upload again. Once confirmed, the database records the request identity before provider work. A duplicate or restart must not repeat generation or delivery. Unknown provider or Telegram delivery states keep their hold for operator investigation. Do not mark an unknown request delivered without independent delivery evidence; do not release it as failed without definitive evidence. The existing owner-only test route and legacy route remain unchanged while the flag is disabled. Promo daily-five accounts fail closed until their quota is integrated; no promo user is charged by this flow.

Do not enable the public flag until testing the exact deployed build against real providers and reviewing the delivered video, audio, translation, account entitlements, credits, failed and uncertain outcomes, and operational reconciliation. Never publish provider keys or personal media in logs or source control.
