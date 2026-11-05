# V265 L2 canonical model bake-off

Geometry-only experimental checkpoint on frozen Stage-1 fixtures. This does
not import a production runtime, render a face, calibrate the fidelity gate,
merge `main`, or deploy.

## Architecture decision

Three representations were executed: current 3DDFA V2 MobileNet x0.5
(40 identity / 10 expression), FaceVerse V4 (156 / 177), and FaceVerse V4 plus
a bounded topology-regularized source residual in canonical 3D coordinates.
FLAME/DECA was rejected before execution because its base model requires manual
registration and acceptance of a separate model license, so it cannot provide
the pinned unattended CI path required here.

FaceVerse V4 + canonical 3D residual is the best geometry candidate. The plain
FaceVerse fit remains too mean-shaped; the residual materially improves every
68-point source self-fit and is stable for the repeated source pairs. It is not
promoted: dense source-surface fidelity is not independently observed, case06
is outside the measured benign deformation envelope, and case08 preserves the
target expression proxy but fails intrinsic mouth identity.

## Source self-reconstruction (mean normalized 68-point error, IOD units)

| Case | 3DDFA | FaceVerse | FaceVerse + 3D residual |
|---|---:|---:|---:|
| 01 | 0.0533 | 0.0683 | 0.0124 |
| 02 | 0.0770 | 0.0677 | 0.0154 |
| 04 | 0.0807 | 0.0532 | 0.0112 |
| 05 | 0.0533 | 0.0683 | 0.0124 |
| 06 | 0.0770 | 0.0677 | 0.0154 |
| 07 | 0.0897 | 0.0753 | 0.0164 |
| 08 | 0.0539 | 0.0628 | 0.0121 |

These are projected 68-point measurements, not a dense scan ground truth.
Accordingly `projected_68_self_reconstruction_sufficient=true` while the hard
`source_self_reconstruction_sufficient=false` remains fail-closed.

## Hard blockers

- **case06:** 17,096 face triangles; one canonical orientation failure; area
  ratio 0.238–5.932 versus normal-case envelope 0.476–2.731; edge stretch max
  2.150 versus 2.037; projected silhouette has a hole. Culling is not counted
  as success, therefore geometry validity is false.
- **case08:** target opening/smile proxy is within the engineering bound, but
  source intrinsic mouth identity is not. Largest failures include
  mouth-to-chin ratio 0.531, philtrum 0.0668 and lip-ratio error 0.0526.
- **case07 parsing:** BiSeNet-ResNet18 emits actual semantic classes including
  glasses. Glasses presence was correct on both positives and four hard
  negatives (dark brows, dark skin/high contrast, grayscale eye shadow,
  no-glasses). It is not validated for ownership: no independent per-pixel
  masks are present, and the CelebAMask-HQ-derived weights lack commercial
  clearance.
- **ownership:** geometry roles are explicit (source brow/eyes/nose/cheeks/
  lips/jaw/chin, target mouth interior), but pixel ownership is deliberately
  unmeasured because rendering did not pass the geometry gate.

Repeated identity hashes are equal for case01/05 and case02/06 for both the
parametric coefficients and canonical residual.

## Memory

Measured process high-water RSS was 596,892 KiB. Geometry arrays alone occupy
78,825,690 bytes; the INT8 regressor file is 99,046,186 bytes and parsing model
53,205,364 bytes. Deleting the regressor session before parsing did not return
enough allocator memory. This exceeds 512 MiB before warming the application,
so production memory qualification is false.

## Reproduction

```bash
python -m venv /tmp/v265-l2
/tmp/v265-l2/bin/pip install numpy==2.1.3 opencv-python-headless==4.10.0.84 onnxruntime==1.20.1 pillow==10.4.0 psutil==6.1.1
/tmp/v265-l2/bin/python -m scripts.v265_matrix_prepare --case case02 --models /tmp/v265-models --output /tmp/v265-results
/tmp/v265-l2/bin/python -m scripts.v265_l2_prepare --output /tmp/v265-l2-assets
PYTHONPATH=. /tmp/v265-l2/bin/python -m scripts.v265_l2_bakeoff --assets /tmp/v265-l2-assets --models /tmp/v265-models --output /tmp/v265-l2-results
```

Pinned URLs and SHA-256 values are in `tests/fixtures/v265_l2_assets.json`.
Per-case scalars, source overlays and parsing masks in this directory are the
negative evidence and must not be replaced by successful examples.
