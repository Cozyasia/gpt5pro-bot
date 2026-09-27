# Self-hosted L2 engineering checkpoint — 2026-09-10

Child draft PR #120, base PR #119 (a50125e). Functional code tested at
432086175ea6833cd50c3df721b5c65c43500f21. GitHub Actions run34511153565:
both isolated-mock (2g) and isolated-mock (4g) SUCCESS, including bootstrap observations.
Earlier run34510715257 also passed both limits. No production changes.

## Actual isolated results

Each Docker runtime has network=none, memory==memory-swap (no swap), cpus=2.
memory.max was2147483648/4294967296; memory.swap.max=0. Both full mock and
bootstrap runs report memory.events max=0, oom=0, oom_kill=0.
Raw sanitized summaries are committed beside this file. They are decoded from the
GitHub job stdout; full job logs/artifacts remain attached to run34511153565.

| Measurement | 2GiB run | 4GiB run |
|---|---:|---:|
| Training peak RSS KiB | 631264 | 634392 |
| Inference/render worker peak RSS KiB | 82852 | 82120 |
| Worker function elapsed ms | 141.85 | 172.25 |
| Full mock cgroup peak bytes | 586166272 | 576249856 |
| MediaPipe+own encoder current RSS KiB | 227676 | 228432 |
| After release current RSS KiB | 174028 | 175764 |
| Sequential bootstrap parser current RSS KiB | 383400 | 385152 |
| Bootstrap cgroup peak bytes | 299343872 | 301424640 |

The full mock pipeline and bootstrap lifecycle are separate sequential containers,
not co-resident with a Telegram daemon. Training has a fresh subprocess; inference
uses ONNX without importing torch. Shared mapped-page charging can make cgroup peak
lower than per-process RSS. Memory limit is enforced independently of that accounting.
No claim of a real-quality high-resolution2GiB production model.

Worker timings include session creation/geometry/render/file writing inside execute,
but exclude Python interpreter/import startup. Approximate reciprocal ceilings are
7.0 /5.8 calls/s for this tiny single-job mock function, NOT service throughput.
Two runner executions differ in timing; more RAM is not shown to improve latency.
Warm forward and cold session timing fields are recorded in worker/result.json CI
artifacts. The earlier224px untrained backbone benchmark remains a separate test.

CPU2GiB/4GiB are practical engineering profiles. Current Render service/worker price
reference:1CPU2GB$25/month;2CPU4GB$85/month, excluding workspace/storage/egress.
Our CI used2CPU quotas for both memory limits; those timings are not Render timings.
https://render.com/pricing (checked2026-09-10)
Small GPU: UNMEASURED; no CUDA device or purchased instance. Runpod A4000 Secure
Cloud advertised from$0.25/hour (~$182.50/730h before extras),16GBVRAM. Hardware
spec is not measured model VRAM, latency or throughput. https://www.runpod.io/gpu-models/rtx-a4000
No hardware purchased/provisioned. CPU path has least operational complexity now;
GPU adds CUDA image/driver/scheduling and requires a separate measured pilot workload.

## Engineering endpoint and remaining work

PASS: generate48 original mock records with train/validation/test ->rights admission
TEST ONLY ->TRAIN-only basis ->all real target losses ->optimizer ->held-out validation
->checkpoint strict reload ->ONNX parity ->separate offline worker ->immutable A to B
cross-view ->local deterministic PNG. Commercial admission rejects mock. Pixel locks
for PERSON-B/neck and repeat PNG are bit-exact. Eight geometry/firewall tests pass.
Actual silhouette loss gradients reach the encoder; no projected-loss placeholders.

This is full training pipeline readiness for the specified v1 record contract, not
proof that arbitrary vendor formats or anatomy models are immediately compatible.
V1 requires consistent expression basis, metric topology and UV correspondence.
Contracted native albedo remains stored; current learned head supervises a16px UV
view. Source image resolution follows admitted records; mock32px is not a production
resolution. Dense high-resolution training memory/runtime still needs profiling.

Not achieved: real pilot split verification, real trained intrinsic identity prior,
anatomical expression semantics, exact source mouth/eye/jaw reconstruction,
case06/07/08 quality PASS, commercially qualified parsing/ownership, full public matrix
quality, production deployment or human A/B. Fixed expression application exists;
richness/identity separation of future anatomical bases remains a data/model task.
Local quality gate requires independent evidence and denies all mock artifacts.
SELF-HOSTED L2 MVP = NO until proper local identity weights and public matrix execution.

Software work no longer depends on MetaHuman/FaceVerse. Next critical input is the
synthetic pilot under reviewed commercial training/derivative-weight rights. High-res
appearance, anatomical correspondence and GPU training must be selected against
that data, not tuned on this procedural mock. Queue/deployment/Telegram document
adapter remain future production infrastructure; no runtime merge was made.

## External tracks

MetaHuman access PENDING; technical GO UNTESTED; no retry or duplicate support email.
FaceVerse rights PENDING; no new licensing email.
Synthesis AI RFQ SENT through Carahsoft; no same-day follow-up.
Second RFQ SENT to3D-Ace (official contact@3d-ace.com); original commissioned assets,
rights and price requested, no commitments. Latest mailbox check found no incoming
reply from these tracks. Pilot price UNKNOWN; commercial data rights PENDING.

No public human sheet generated; mock candidate PNGs are diagnostic artifacts only.
Main remains c4bda09a98557e1bdea46338bccf66d8b6e6ed61. Render frozen.
