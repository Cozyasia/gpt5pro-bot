# SELF-HOSTED L2 QUALITY TRACK — first trained candidates, NO V0

Code tested: `54c9bde087f248c9a031ab4c289561b64fa358e0`, PR #120.
Production main and Render are unchanged; no merge/deploy. Parent #119 untouched.
External tracks remain optional. Inbox searches found no matching replies;
MetaHuman/FaceVerse PENDING, Synthesis AI/3D-Ace RFQs SENT, pilot rights PENDING.
No follow-up, purchase, paid GPU or contract was initiated.

## Decision

Own RGB encoders now learn nontrivial held-out procedural identity geometry.
They are NOT V0: controlled pose drift is 2.5–3.1mm (policy limit .5mm), glasses
frame IoU is zero, albedo does not materially improve on a TRAIN mean texture,
and the patch does not support full intrinsic lip/cavity qualification.
Local frames IoU=0; CI Mobile128 frames IoU=.00637, also unacceptable.
Do not run the real frozen matrix or create a human sheet from these weights.

Parametric MobileNetV3-small is the provisional family. Local /256 is best in
geometry; isolated CI /128 and /256 are effectively tied (1.3472/1.3469mm). Keep
/128 as the smaller comparison baseline and retain /256, without declaring a
robust capacity winner. Learned residual/256 improves local yaw drift slightly
but worsens geometry/projection error and costs more. No candidate wins acceptance.
No larger latent sweep: the generated geometry has rank36, not rank128/256.

## What was executed

- Original generator v3: 24 morphology + 12 bounded expression-orthogonal residual
  modes; 8 independent expression modes; no third-party faces, geometry or weights.
- 128 identities ×8 views =1,024 records, 64px RGB; 80/24/24 disjoint identities.
  Checksum manifest and original provenance are preserved in `final-v3`.
- Native grids 2,009/3,840 and 5,265/10,240 vertices/triangles; separate numerical
  capacity, raster and update/export memory measurements. Full encoder training
  was performed on 2,009 only. Higher resolution's one-update test is NOT a
  trained-quality comparison. Coarse→fine geometry interpolation RMSE is .0758mm,
  much smaller than current RGB encoder reconstruction error.
- Four fixed 12-epoch experiments; validation-only checkpoint choice; sealed test
  identities evaluated separately. Actual albedo64/128 and parsing15 optimization.
- Controlled interventions for all four models, each on 24 sealed identities:
  neutral/smile/open/asymmetric/yaw/light/glasses; independent B projection and
  silhouette from immutable source-smile inference. B pixels never feed that
  identity inference. Additional B inferences measure nuisance drift separately.
- Reload, deterministic repeat inference, native/ONNX parity and hash manifests.
  Checkpoints are experimental trained candidates, explicitly `v0=false`.

| Model | Geometry RMSE mm | Relative to mean | Yaw drift mm | Smile drift mm | B projection RMSE px |
|---|---:|---:|---:|---:|---:|
| Mobile128 parametric |1.370|.448|2.906|.0455|.293|
| Shuffle128 parametric |1.553|.508|3.054|.0852|.339|
| Mobile256 parametric |1.269|.415|2.714|.0255|.265|
| Mobile256 learned |1.338|.438|2.508|.0347|.282|

Mean-prior geometry RMSE:3.055mm. Best per-region RMSE mm: jaw1.228, chin1.683,
nose1.768, mouth1.368, eyes1.137, cheeks1.126, brows.780.
Small smile drift does NOT prove intrinsic lip identity. Width/separation and
philtrum/nose/chin distances are recorded, but separation is explicitly not lip
thickness ratio. Cupid-bow fidelity/teeth exposure are not qualified.

## Geometry findings and correction

Initial signed displacement fields were discontinuous through the midline.
Their negative evidence is retained under `preliminary-v1`; v1 also omitted smile
from training. Corrected v3 uses continuous tanh fields and explicit smile/open
schedule. No raster triangle culling repaired these errors.

For EACH resolution, an independent 256-sample calibration and 32-sample stress
show zero orientation failures, zero interior raster holes and zero samples
outside the observed envelope. The patch numerical stress passes. This does NOT
qualify a full anatomical surface or real case06. In particular, finer topology
still has local compression down to .138 in calibration: record the distribution,
do not call it a universal human-face deformation envelope.

The suite's conservative V0 gate retains full-surface case06=false; the separate
`benign-envelope.json` records the narrower positive patch result. There is no
contradiction: patch topology validity is insufficient for full-face acceptance.

## Appearance/accessories limits

Albedo MSE: .004484/.004229/.004396/.004615 across the four runs. TRAIN mean
albedo on held-out128px GT is .004306; these results do not show useful high-detail
appearance learning. Resolutions64/128 are implemented, but representation and UV
resolution change together in run4; no isolated causal UV-quality claim.

Parsing was trained, but frames IoU=0 in all final models. Hair/neck/teeth/mouth
interior/occlusion are absent from generated geometry; do not claim supervision
or ownership for absent classes. Glasses are UV decals, not physical frame/lens
layers. This is not a complete anatomical pretraining factory yet.

## Memory and reproducibility

Local full training peak RSS: ~990MiB parametric, ~1,028MiB learned. Separate ONNX
process: Mobile256 ~64.2MiB peak, 2.56ms warm inference; learned ~72.9MiB,5.52ms.
These inference timings exclude detection, raster, parsing bootstrap and delivery.
The 2,009/5,265 microbench uses ~384/~391MiB peak for one batch16 update; ONNX-only
~64.2/~65.4MiB. Raster ~.3/.62s at64px. Local RSS is NOT isolated qualification.
The dedicated new CI suite enforces Docker memory=2g, swap=2g, CPUs=2, network=none.
CI run34705694729 / job103585209239 completed SUCCESS on the code SHA above.
Actual cgroup peak1,236,754,432 bytes (~1.152GiB), memory.max2,147,483,648;
swap.max0; memory.events max/oom/oom_kill all0. Full raw parsed CI reports are
in final-v3/ci-isolated.json. CI quality gate remains v0=false.

CI geometry RMSE mm: Mobile1281.3472, Shuffle1281.5921, Mobile2561.3469,
learned2561.4559. The dataset manifest hash is IDENTICAL to the local run; numeric
training outcomes vary across CPU environments. Repeat inference within each
environment is deterministic and native/ONNX parity passes (max<=3.34e-6).
Do not claim cross-hardware bit-exact training reproducibility.

Trained checkpoints/ONNX files and manifests were uploaded as artifact10302315527
(90-day retention): https://github.com/Cozyasia/gpt5pro-bot/actions/runs/34705694729/artifacts/10302315527
Artifact ZIP SHA256 ac66bf9f29025eb06d41aeb3849dc663a40a318fcf62b94d9e832d3f71abe0d7.

CUDA container/config exists with `--device cuda` and deterministic CUBLAS setup;
no GPU run, latency, VRAM or paid compute is claimed.

Canonical reproduction:

```sh
python -m experiments.v265_quality.run_suite /results/quality-v3
python -m experiments.v265_quality.controlled /results/quality-v3/corpus /results/quality-v3/shuffle128
python -m experiments.v265_quality.controlled /results/quality-v3/corpus /results/quality-v3/mobile256
python -m experiments.v265_quality.controlled /results/quality-v3/corpus /results/quality-v3/learned256
```

Run extra diagnostic scripts via `python -c` + `runpy.run_path` from repo root,
adding arguments through sys.argv, NOT by placing repo root on PYTHONPATH.
A local additional audit initially used `PYTHONPATH=.` and inadvertently triggered
legacy sitecustomize hooks. Its result was discarded and the audit repeated without startup path injection.
No production service or deployment was changed. The training containers copy only
experiments and never include the legacy sitecustomize module.

## What is still unfinished

1. Full anatomical topology: volumetric mouth, independently represented lip
   surfaces/ratios, eyes/eyelids, nasal cavities, physical accessory layers.
2. Factorial anatomy/lighting/accessory diversity beyond the rank36 relief family;
   calibrated intrinsic mouth metrics and full coverage ownership.
3. Pose-invariant learned identity; meaningful appearance and accessory masks.
4. Supplier-data finetune/admission using executed rights, external cross-view and
   final real frozen matrix. The existing trainer entrypoint is preserved; no new
   fully qualified real-pilot one-command wrapper is claimed by `run_suite`.
5. Full high-resolution quality training and real-human identity acceptance.

The next task is anatomy/data and learned invariance, not another module redesign
or tuning this relief dataset's training loss to make a V0 announcement.
