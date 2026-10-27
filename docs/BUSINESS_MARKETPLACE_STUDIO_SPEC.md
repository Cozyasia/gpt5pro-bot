# Business Studio / Marketplace Product Cards — approved specification

Status: approved for implementation. This document does not imply the feature is deployed.

## Navigation
Business menu: Documents; Analytics; Presentations/Catalogs; Marketplace AI Product Cards; Business AI Video; Design; Speech/Text; Free Request.
Production menu: Property AI walkthrough; Product advertising; Service advertising (replaces overlapping Property advertising); UGC; Expert; Brand; Reels; Custom; Director.
Three ad variants becomes an option, not a separate workflow. Reuse existing property and product generation routes; do not fork engines.

## Marketplace workflow
1. Select output: studio photos, infographic cards, video, complete package.
2. Select marketplace: Wildberries, Ozon, Yandex Market, Amazon, generic. Store requirements in versioned configurable presets; validate before export.
3. Receive original photos (single, album, multiple messages) and voice/text brief. Speech recognition must feed the same normalized brief path as text. Keep draft state persistent.
4. After each upload send count and explicit Add more / Continue buttons, without requiring the user to type a magic phrase. Album aggregation must be idempotent.
5. Extract product type and only visually supported attributes; ask for material, measurements, quantity, brand, claims and other unknowns. Do not invent facts, labels or unseen product geometry.
6. Show editable shot plan: hero, alternative angles, details, lifestyle, infographic. Distinguish generated views from verified views.
7. Infographic mode: auto suggested copy or manual text; render Cyrillic as a separate editable graphics/text layer rather than relying on image model lettering.
8. Video: turntable 360, camera orbit, or multi-scene commercial. Exact 360 requires sufficient real angles or capture video; disclose speculative unseen geometry otherwise.
9. Preview itemized provider cost and credits before explicit confirmation. Charge using existing ledger, idempotency keys and refund/failed-task semantics. No silent debits.
10. Export validated JPG/PNG/MP4, description and ZIP package; preserve source references and project history.

## Acceptance criteria
- Same existing Telegram bot; no duplicate token poller.
- No regressions in existing property walkthrough, product ad, other business workflows.
- Both voice and text brief, multi-image uploads, Continue/Back/Cancel/resume work.
- Source product appearance preserved; unverifiable details flagged.
- Marketplace constraints validated against current platform rules, not hardcoded guesses.
- Provider errors, retries, costs, cancellation and credits covered by tests.
- Roll out behind a feature flag; deploy only after tests and production readiness review.
