# Render memory hardening runbook

## Incident summary

The production Web Service is configured as `starter` in `render.yaml`. The v154 release added `rembg[cpu]`, installed ONNX Runtime, cached a `u2net_human_seg` inference session, and changed the selfie cutout order to local rembg before PhotoRoom. A single in-process segmentation request can therefore push a 512 MB web instance over its hard memory limit.

Two existing settings looked safe but did not control the v154 path:

- `BG_DISABLE_LOCAL_REMBG=1`
- `LOCAL_REMBG_ENABLED=0`

v154 used `CELEBRITY_V142_LOCAL_REMBG_FALLBACK` and `CELEBRITY_V143_CUTOUT_PROVIDERS`, and set them to local-rembg-enabled defaults. The memory alert is therefore consistent with a release regression, not merely unexplained traffic.

## Immediate production settings

Change the live `gpt5pro-bot` instance type in the Render Dashboard from **Starter** to **Standard**. The web service should have 2 GB RAM while media traffic remains in the same process.

Set these environment values explicitly:

```env
BG_DISABLE_LOCAL_REMBG=1
LOCAL_REMBG_ENABLED=0
BG_FORCE_LOCAL_REMBG=0
CELEBRITY_V142_LOCAL_REMBG_FALLBACK=0
CELEBRITY_V143_CUTOUT_PROVIDERS=photoroom
CELEBRITY_V154_MAX_CONCURRENCY=1
MEMORY_SOFT_LIMIT_MB=1500
MALLOC_ARENA_MAX=2
OMP_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1
MKL_NUM_THREADS=1
NUMEXPR_NUM_THREADS=1
```

`MEMORY_SOFT_LIMIT_MB=1500` is intended for a Standard 2 GB instance. Do not use that value on Starter; use `380` temporarily if an emergency deploy must remain on 512 MB.

## What this change set does

1. Removes `rembg[cpu]` and ONNX Runtime from the latency-sensitive web dependency set.
2. Keeps the optional CPU segmentation backend in `requirements-media-worker.txt` for a separately sized worker.
3. Applies the global background-removal policy after all historical selfie overlays, so v154 can no longer silently re-enable local rembg.
4. Serializes v154 heavy generation by default.
5. Reads current Linux RSS and refuses a new heavy request at the configured soft limit, before Render performs a hard restart.
6. Logs RSS at the beginning and end of each v154 generation.

## Deployment validation

After merging and deploying, verify the logs contain a line similar to:

```text
memory_guard installed version=v155-render-memory-hardening-2026-07-22 local_rembg=disabled providers=photoroom concurrency=1
```

Then run:

- `/diag_bg`: local rembg must be disabled and a missing `rembg` import is expected in the web service.
- `/diag_selfie_v154`: provider order must resolve to PhotoRoom for the live operation.
- One normal text request, one PDF request, one background removal, and one celebrity selfie.
- Two simultaneous celebrity-selfie requests: one must wait; the process must remain available.

Review Render **Metrics → Memory** for at least one complete media request. Baseline memory should no longer jump when the web process starts, and no ONNX model should be resident.

## Target production architecture

The durable architecture is:

```text
Telegram webhook Web Service
  -> validates request, charges/reserves credits, creates job
  -> durable queue (Render Key Value / Redis)
  -> isolated Media Worker (Standard or Pro)
  -> provider APIs / optional ONNX segmentation
  -> durable result record
  -> Telegram delivery
```

The web service should never download or transform large video in memory. Large files should stream to `/tmp` or object storage. CPU inference, ffmpeg muxing, PDF rendering, and long media polling should run in a worker with independent concurrency and memory limits.

## Rollback

If PhotoRoom is unavailable, do not re-enable ONNX inside the web process. Deploy an isolated worker using:

```bash
pip install -r requirements-media-worker.txt
```

Only that worker should receive all three explicit local-rembg opt-ins:

```env
BG_DISABLE_LOCAL_REMBG=0
LOCAL_REMBG_ENABLED=1
CELEBRITY_V142_LOCAL_REMBG_FALLBACK=1
```
