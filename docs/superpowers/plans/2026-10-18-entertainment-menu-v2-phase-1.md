# Entertainment Menu V2 — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat and duplicated `🔥 Развлечения` interface with one feature-flagged result-first menu that reuses every currently working media flow and preserves all legacy callbacks.

**Architecture:** Define menu data in a small import-safe package and render it to Telegram keyboards through one adapter. `main.py` remains the owner of runtime handlers, but it delegates V2 menu construction and callback classification to the package; existing `fun:*` actions remain unchanged. This phase ships navigation and working aliases only; games/leisure workflows, product templates, orchestration, and new providers receive separate plans.

**Tech Stack:** Python 3.11, python-telegram-bot 21.6, stdlib `dataclasses`/`unittest`, existing monolithic `main.py`.

**Spec:** `docs/superpowers/specs/2026-10-18-entertainment-menu-neuro-production-design.md`

## Global Constraints

- Do not change the persistent root menu or its labels.
- Do not remove or rename any existing `fun:*`, `act:fun:*`, command, payment, or generator handler.
- Do not expose `🎤 Фото поёт · Beta` in the V2 menu.
- Use the approved names `🎬 Нейро Продакшен`, `🎛 Режим режиссёра`, and `🧠 Выбрать модель`; never use `Автостудия` or `Создать видео по идее`.
- Long or primary Telegram actions occupy their own row; no row contains more than two buttons.
- Every callback payload must be at most 64 UTF-8 bytes.
- An unavailable service is explicitly marked `· Скоро`, cannot reserve credits, and cannot start a provider job.
- `ENTERTAINMENT_MENU_V2=0` is the default; false values are `""`, `"0"`, `"false"`, `"no"`, and `"off"`, case-insensitive.
- Existing credit reserve/commit/release behavior is not modified in this phase.
- Production remains unchanged until branch tests and a test-user smoke check pass.

## Review Focus

- Malformed or unknown `ent:*` callback: acknowledge it once, show the V2 root menu, and start no job.
- Stale V2 button after the feature flag is disabled: acknowledge it once, show the legacy entertainment menu, and start no job.
- Repeated taps on a `· Скоро` button: show information only; never create state that a payment/generator handler can consume.
- Entry through any of the existing text button, command, or `mode:fun` paths: render the same menu selected by the feature flag.
- Return from a nested menu while a separate paid/media flow exists: change only `ent_nav_menu`; do not clear unrelated `user_data`.

---

## File Map

- Create `neyrobot_prod/entertainment/__init__.py`: stable public exports for the package.
- Create `neyrobot_prod/entertainment/catalog.py`: immutable menu/button specifications and feature-flag parsing.
- Create `neyrobot_prod/entertainment/keyboards.py`: Telegram markup rendering and callback classification.
- Modify `main.py`: replace competing menu entry points with one compatibility wrapper and register `ent:*` handling before `fun:*`.
- Create `tests/test_entertainment_catalog.py`: pure catalog and rendering contracts.
- Create `tests/test_entertainment_main_wiring.py`: AST/source-level compatibility and handler-order contracts.

The next independent plans will cover: structured games and `Чем заняться`; productized music/photo/video presets; `Нейро Продакшен` orchestration and economics; new dubbing/multi-reference/lip-sync integrations.

### Task 1: Immutable Menu Catalog

**Files:**
- Create: `neyrobot_prod/entertainment/__init__.py`
- Create: `neyrobot_prod/entertainment/catalog.py`
- Test: `tests/test_entertainment_catalog.py`

**Interfaces:**
- Produces: `MenuButtonSpec(text: str, callback_data: str, status: str = "active")`.
- Produces: `MenuSpec(menu_id: str, title: str, intro: str, rows: tuple[tuple[MenuButtonSpec, ...], ...])`.
- Produces: `get_menu(menu_id: str) -> MenuSpec`.
- Produces: `iter_menus() -> tuple[MenuSpec, ...]`.
- Produces: `entertainment_menu_v2_enabled(environ: Mapping[str, str] | None = None) -> bool`.

- [ ] **Step 1: Write failing tests for feature-flag parsing**

Add `EntertainmentFlagTests.test_default_is_disabled` and `test_truthy_and_falsey_values`. Assert the default is false, the five exact false values from Global Constraints are false, and `"1"`, `"true"`, `"yes"`, `"on"` are true.

- [ ] **Step 2: Run the flag tests and verify failure**

Run: `python -m unittest tests.test_entertainment_catalog.EntertainmentFlagTests -v`
Expected: FAIL because `neyrobot_prod.entertainment.catalog` does not exist.

- [ ] **Step 3: Implement the immutable types and flag parser**

Implement the interfaces above in `catalog.py`; export them from `__init__.py`. Reject an unknown `menu_id` with `KeyError`.

- [ ] **Step 4: Write failing tests for the approved root menu**

Add `EntertainmentCatalogTests.test_root_menu_matches_approved_layout`. Assert exact rows:

```python
[
    ["🎬 Нейро Продакшен"],
    ["🔥 В тренде", "🎥 Создать видео"],
    ["📸 Фото и эффекты", "🎵 Музыка и песня"],
    ["🎮 Игры с AI", "🎉 Чем заняться"],
    ["📝 Свой запрос"],
    ["⬅️ Назад"],
]
```

Assert callbacks are respectively `ent:menu:production`, `ent:menu:trends`, `ent:menu:video`, `ent:menu:photo`, `fun:music`, `fun:quiz`, `fun:ideas`, `fun:free`, and `mode:root`. The last callback deliberately leaves the entertainment section through the existing root-menu handler.

- [ ] **Step 5: Define the V2 root and Phase-1 submenus**

Create catalog entries `root`, `production`, `trends`, `video`, and `photo`.

Use these active mappings:

- production: `🎛 Режим режиссёра → fun:video_director`;
- trends: `✨ Фото оживает → fun:revive`, `🗣 Фото говорит → fun:avatar`, `⭐ Селфи со звездой → fun:aiselfie`, `✈️ Travel Reel → fun:reels`;
- video: `Видео по тексту или голосу → fun:textvideo`, `Оживить фото → fun:revive`, `Reels / Shorts → fun:reels`, `Мини-фильм → fun:film`, `Сценарий и раскадровка → fun:storyboard`, `Авторежиссёр → fun:video_director`, `Автомонтаж → fun:video_montage`, `Выбрать модель → fun:textvideo`;
- photo: `Создать изображение → fun:img`, `AI-селфи → fun:aiselfie`, `Замена лица → fun:faceswap`, `Удалить фон → fun:removebg`, `Заменить фон → fun:replacebg`.

All other approved submenu entries use a unique `ent:soon:<service_id>` callback, visible label suffix `· Скоро`, and status `soon`. Every submenu ends with `ent:back:root`, which returns to the V2 entertainment root without touching other flow state.

- [ ] **Step 6: Add and run catalog integrity tests**

Add tests asserting:

- `menu_id` values are unique;
- labels are unique within each menu;
- callbacks are no longer than 64 UTF-8 bytes;
- rows contain one or two buttons;
- every `soon` button has both `· Скоро` and `ent:soon:`;
- no label contains `Автостудия`, `Создать видео по идее`, or `Фото поёт`;
- exactly one V2 button has the meaning “video from text or voice”.

Run: `python -m unittest tests.test_entertainment_catalog -v`
Expected: PASS.

- [ ] **Step 7: Commit the catalog**

```bash
git add neyrobot_prod/entertainment tests/test_entertainment_catalog.py
git commit -m "feat: add entertainment menu v2 catalog"
```

### Task 2: Telegram Rendering and Callback Classification

**Files:**
- Create: `neyrobot_prod/entertainment/keyboards.py`
- Modify: `neyrobot_prod/entertainment/__init__.py`
- Test: `tests/test_entertainment_catalog.py`

**Interfaces:**
- Consumes: `get_menu(menu_id) -> MenuSpec` from Task 1.
- Produces: `build_keyboard(menu_id: str, button_cls: type, markup_cls: type) -> object`.
- Produces: `EntertainmentCallback(kind: Literal["menu", "soon", "back", "unknown"], target: str)`.
- Produces: `classify_callback(data: str) -> EntertainmentCallback`.

- [ ] **Step 1: Write failing rendering tests**

Add `EntertainmentKeyboardTests.test_renderer_preserves_rows_text_and_callbacks` using local fake button/markup classes. Assert the rendered `root` markup exactly matches the catalog and does not import or initialize `main.py`.

- [ ] **Step 2: Run the rendering test and verify failure**

Run: `python -m unittest tests.test_entertainment_catalog.EntertainmentKeyboardTests -v`
Expected: FAIL because `keyboards.py` does not exist.

- [ ] **Step 3: Implement dependency-injected keyboard rendering**

Implement `build_keyboard` without importing Telegram at module import time. Construct each button as `button_cls(text, callback_data=callback_data)`, then `markup_cls(rows)`.

- [ ] **Step 4: Write failing callback-classification tests**

Assert:

- `ent:menu:video → ("menu", "video")`;
- `ent:soon:ugc_ad → ("soon", "ugc_ad")`;
- `ent:back:root → ("back", "root")`;
- unknown menu IDs, empty targets, extra segments, and non-`ent:` values classify as `unknown`.

- [ ] **Step 5: Implement strict callback classification**

Only accept catalog menu IDs for `menu`/`back`. For `soon`, accept service IDs matching `[a-z0-9_]{1,40}`. Do not raise for user-controlled callback data.

- [ ] **Step 6: Run tests and commit**

Run: `python -m unittest tests.test_entertainment_catalog -v`
Expected: PASS.

```bash
git add neyrobot_prod/entertainment
git add tests/test_entertainment_catalog.py
git commit -m "feat: render and classify entertainment menus"
```

### Task 3: Main Runtime Compatibility Wrapper

**Files:**
- Modify: `main.py:3736-3780`
- Modify: `main.py:5706-5738`
- Modify: `main.py:18740-19003`
- Modify: `main.py:19590-19605`
- Create: `tests/test_entertainment_main_wiring.py`

**Interfaces:**
- Consumes: `entertainment_menu_v2_enabled`, `build_keyboard`, and `classify_callback`.
- Produces: `_legacy_fun_quick_kb() -> InlineKeyboardMarkup`.
- Produces: `_fun_quick_kb() -> InlineKeyboardMarkup` as the single compatibility entry point.
- Produces: `async on_cb_entertainment(update, context) -> None`.

- [ ] **Step 1: Write failing AST tests for a single canonical menu owner**

Parse `main.py` and assert there is exactly one top-level function named `_fun_quick_kb`, exactly one `_legacy_fun_quick_kb`, and `_mode_kb("fun")`, `cmd_mode_fun`, `on_mode_fun_text`, and `on_btn_fun` all reach the compatibility function rather than maintaining their own entertainment rows.

- [ ] **Step 2: Run the wiring tests and verify failure**

Run: `python -m unittest tests.test_entertainment_main_wiring -v`
Expected: FAIL because `main.py` currently defines `_fun_quick_kb` twice and also embeds a separate `_mode_kb("fun")` menu.

- [ ] **Step 3: Consolidate the three current menu definitions**

Keep the current active 16-row menu body as `_legacy_fun_quick_kb`. Remove the earlier duplicate `_fun_quick_kb` definition. Make the single canonical `_fun_quick_kb` return:

- V2 `build_keyboard("root", InlineKeyboardButton, InlineKeyboardMarkup)` when the flag is enabled;
- `_legacy_fun_quick_kb()` otherwise.

Change the `fun` branch of `_mode_kb` to return `_fun_quick_kb()`. Do not alter study, work, or medicine branches.

- [ ] **Step 4: Write failing async handler tests with fakes**

Test `on_cb_entertainment` behavior through an AST-extracted function or minimal injected namespace:

- `ent:menu:video` stores `context.user_data["ent_nav_menu"] == "video"` and replies with the video keyboard;
- `ent:back:root` returns the root keyboard;
- `ent:soon:ugc_ad` answers and replies with “готовим”/“скоро”, does not add payment/generator state, and retains the current navigation menu;
- unknown callback replies with the root keyboard;
- with V2 disabled, every `ent:*` callback replies with the legacy keyboard;
- pre-existing unrelated keys such as `credit_reservation_id` and `awaiting_music_video_video_brief` are unchanged.

- [ ] **Step 5: Implement `on_cb_entertainment`**

The handler must call `q.answer()` once. For menu/back routes, update only `ent_nav_menu` and send the catalog intro plus keyboard. For `soon`, send an informational message and the current V2 keyboard. For unknown routes, send the V2 root. When the feature flag is disabled, show the legacy keyboard and return before classification.

Do not call `_clear_transient_flows` inside this navigation handler.

- [ ] **Step 6: Register the V2 callback before legacy and catch-all handlers**

Add `CallbackQueryHandler(on_cb_entertainment, pattern=r"^ent:")` immediately before the existing `^fun:[a-z_]+$` handler. Keep the existing `fun:*` handler pattern and catch-all unchanged.

- [ ] **Step 7: Update entry copy without changing the root reply keyboard**

When V2 is enabled, entertainment intro copy is:

```text
🔥 Развлечения

Создавайте видео, фото, музыку и готовые проекты — от идеи до результата. Выберите, что хотите получить.
```

When disabled, retain the current text. The persistent `main_kb` remains byte-for-byte unchanged.

- [ ] **Step 8: Run focused tests and commit**

Run: `python -m unittest tests.test_entertainment_catalog tests.test_entertainment_main_wiring -v`
Expected: PASS.

```bash
git add main.py neyrobot_prod/entertainment tests/test_entertainment_main_wiring.py
git commit -m "feat: wire entertainment menu v2 behind flag"
```

### Task 4: Regression and Release Gate

**Files:**
- Modify: `tests/test_entertainment_main_wiring.py`
- Modify: `docs/superpowers/specs/2026-10-18-entertainment-menu-neuro-production-design.md` only to mark Phase 1 implementation status after verification.

**Interfaces:**
- Consumes: all Phase-1 interfaces.
- Produces: a tested branch with no production deployment.

- [ ] **Step 1: Add registration-order and legacy-callback regression tests**

Assert in the AST/source:

- `on_cb_entertainment` registration precedes `on_cb_fun`;
- the existing `^fun:[a-z_]+$` registration remains;
- all legacy actions used by active V2 buttons have a branch in `on_cb_fun`;
- the root menu labels outside entertainment are unchanged;
- neither `main.py` nor the new package changes reserve/commit/release functions.

- [ ] **Step 2: Run all entertainment and existing menu tests**

Run:

```bash
python -m unittest   tests.test_entertainment_catalog   tests.test_entertainment_main_wiring   tests.test_music_video_menu   tests.test_music_video_prompt_ux   tests.test_start_welcome_timeout_guard -v
```

Expected: PASS.

- [ ] **Step 3: Run the full repository suite**

Run: `python -m unittest discover -s tests -v`
Expected: all tests PASS. Any pre-existing failure must be reproduced on `main@5a7480e05052e4a4f5cb8e64715ebaf945083304` before it may be classified as unrelated.

- [ ] **Step 4: Verify both flag states locally**

Build the application once with `ENTERTAINMENT_MENU_V2=0` and once with `ENTERTAINMENT_MENU_V2=1`, using test-safe environment values. Confirm no duplicate handler warning and no provider call during startup.

- [ ] **Step 5: Update implementation status and commit**

Record the verified commit SHA and test commands in the spec’s rollout section without changing approved product decisions.

```bash
git add docs/superpowers/specs/2026-10-18-entertainment-menu-neuro-production-design.md
git add tests/test_entertainment_main_wiring.py
git commit -m "test: verify entertainment menu v2 rollout gate"
```

- [ ] **Step 6: Stop before production**

Open a reviewable PR from `feature/entertainment-menu-neuro-production` to `main`. Do not merge, deploy, or enable `ENTERTAINMENT_MENU_V2` until branch review and a named test-user smoke plan are approved.
