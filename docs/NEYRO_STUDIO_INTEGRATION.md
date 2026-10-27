# Neyro Studio Mini App — integration checklist

Status: **prototype, not production enabled**.

## Existing changes
- `web/studio_menu.html`: mobile catalog with 11 categories and optional HTTPS video previews.
- `neyrobot_prod/studio_menu_navigation.py`: strict allowlist for a small subset of routes.
- `tests/test_studio_menu_navigation.py`: navigation payload unit tests.

## Critical integration constraints
1. Do not enable `navigationEnabled` until a Telegram server handler is registered and tested. Telegram `WebApp.sendData` is supported for Mini Apps launched through a keyboard button; it is not a universal transport for menu-button or inline-button launches. For those contexts, use authenticated HTTPS backend requests with server-side Telegram `initData` validation, or a separately verified deep-link handoff.
2. Never trust a route from browser JS by itself. Validate authenticated Telegram identity, current user entitlements, payment status, medical consent and callback dispatch on the server.
3. Do not send medical reports, patient identifiers, diagnoses, or other sensitive content in `sendData`, query parameters or analytics.
4. Do not expose unpublished provider capabilities as available. Verify real callback handlers in current production `main.py` before adding to the allowlist.
5. Host media on a stable HTTPS origin. Publish only authorized, anonymized medical examples and properly licensed demonstrations. Do not store user-generated videos in the repository.
6. Use the original Neyro-Botik brand asset as the single character source. Variants (doctor, director, photographer, musician) must retain the same visual identity.
7. Preserve existing payment, medical-card, subscription and generation handlers. Avoid modifying `main.py` until the dispatch integration is reviewed.

## Acceptance tests before merging
- Launch from the **actual** Telegram entry point on Android and desktop.
- Verify each enabled category reaches its correct handler and that disabled categories cannot trigger actions.
- Check unauthorized and expired subscription flows, including medical consent.
- Check loading, network failure, missing media, accessibility and keyboard navigation.
- Confirm CI unit tests, Render health, rollback procedure, and user balances.
- Attach verified sample media and record provenance.

## Deployment
Keep this PR in draft until server integration and end-to-end Telegram tests pass.
