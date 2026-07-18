# VALIDATION — v119 Production Hardening

## 1. Deployment

1. Render: `Manual Deploy → Clear build cache & deploy`.
2. `/version` must show `v119-production-hardening-2026-07-18`.
3. `/diag_prod` must show:
   - `sqlite_journal=wal`
   - `payments_patch=on`
   - `payment_guard=on`
   - `jobs_patch=on`
   - `concurrency_guard=on`
   - `medical_text_route=v119`
   - `medical_image_route=v119`

## 2. Medical Card regression test

### Unlimited/owner account

1. Open **Медицина → Анализы**.
2. Upload a PDF or clear photo.
3. After the final medical answer, expect exactly one prompt:
   `Сохранить оригинал, распознанные данные и этот разбор в медицинскую карту?`
4. Without prior consent, expect **Создать карту и сохранить**.
5. Accept consent, save, then open the Medical Card and verify the document appears.
6. `/diag_medcard` should show `entitled=on` and `public_*_handler=v119`.

### FREE/START account

1. Upload a medical PDF/photo.
2. The analysis must still be delivered.
3. After the answer, expect one PRO/ULTIMATE Medical Card explanation with plan buttons.
4. No raw pending medical payload should remain; `/diag_medcard` should show `pending=off`.

## 3. Payment idempotency

Test with a low-value sandbox/test payment where available.

1. Complete one payment.
2. Reopen/check the same payment or allow two pollers to see `succeeded`.
3. Subscription duration and credits must change only once.
4. Replayed Telegram successful-payment update must answer that the payment was already processed.
5. A stale Telegram invoice with a wrong amount must be rejected during pre-checkout.
6. Test a quarter/year Telegram invoice: the guard must accept the server-side discounted amount, not multiply the monthly WebApp price.

## 4. Durable jobs

1. Start Suno or one text/image-to-video task.
2. `/diag_jobs` should list the provider task while it is polling.
3. Restart the service after the provider task ID has been created.
4. On startup the bot should resume polling and either deliver the result or send an explicit recovery failure message without a second credit charge.

## 5. SQLite and backups

1. `/backup_now` from the OWNER_ID account.
2. Verify `/data/backups` contains:
   - `subs-*.sqlite3`
   - `manifest-*.json`
   - a Medical Card Fernet key copy when a key exists.
3. Restart Render and confirm subscriptions, wallet, chats and Medical Card remain available.

## 6. Concurrency

1. From one account start two heavy generations quickly.
2. The second must receive the queue message and wait.
3. From several accounts confirm no more than the configured global heavy-task limit runs concurrently.

## 7. Core smoke test

- `/start`, modes and bot menu
- ordinary GPT text and image analysis
- voice STT and optional TTS
- image generation
- remove/replace background
- Runway/Kling text-to-video and image-to-video
- Suno
- FaceSwap single-person test
- plans, balance and credit packages
- Presentation Studio project isolation test (separate follow-up validation)
