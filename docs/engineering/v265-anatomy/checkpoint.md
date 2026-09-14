# ANATOMY + INVARIANCE: generator admission rejected

Owner: PR #120, v265-self-hosted-l2; parent baseline 8b1b92268d50b35aa30bf46140afa98572aed033.
Production frozen; no runtime integration, merge or deploy. RELIEF-V3 remains unchanged,
including its four trained candidates and negative pose/parsing/albedo results.

This is an original anatomical **assembly prototype**, not a qualified full anatomical
face generator. It adds five apertures with inset rims/cavities, separate eye supports,
lip surfaces, teeth ellipsoids, and physical frame/lens primitives. It has 5,644 vertices,
10,990 triangles, 80 nonlinear controls (16 regions x 5). These controls are NOT proof
of 80 independently realistic anatomical degrees of freedom. Nasolabial morphology,
lip/cavity contact, closed eyelid contact, component intersections, transparent-layer
visibility, albedo and complete anatomical annotation still require implementation or validation.

## Measured blocker

The recovered polar ring parameterization collapses two triangles (8171, 8172).
Preserving the unique boundary coordinates fixes neutral degeneracy: zero degenerate,
nonmanifold or inconsistently wound edges; 256 expected outer boundary edges.
That structural check does NOT establish no self-intersections or critical silhouette holes.

On 32 withheld identity expression stresses, there are **25 normal-orientation violations**,
all attributed to lip triangles. Isolated mouth opening reproduces triangle 8111 failure
on identity417. A continuous extension into the cavity worsens this to **298 violations**.
Both experiments are retained, neither admitted to training. The normal-dot test is a
conservative orientation diagnostic, not by itself a complete 3D intersection/foldover proof.
A valid mouth articulation/contact construction remains the concrete geometry blocker.
No triangles are culled, no gate is loosened, and no RGB corpus or encoder training is run.

512 neutral geometry identities were audited, **zero rendered training examples**.
128 roots x4 descendants;320/96/96 identities in train/validation/test, roots80/24/24.
TRAIN-only numerical span rank is319 at relative singular-value tolerance1e-5. This
nonlinear finite-sample span is NOT intrinsic/anatomical dimension; energy ranks are
reported separately in audit.json. Rank alone is not a capacity acceptance criterion.

Memory in audit.json is local process peak RSS, NOT an isolated2GiB training benchmark.
A/B invariance, Mobile128/256, heldout encoder RMSE, pose/expression drift and ONNX
are NOT_MEASURED on V4. Case06 and case08 are not qualified; V0 remains NO.
No public real matrix or human sheet. External procurement statuses are carried from
last checkpoint, not refreshed by this geometry run; no duplicate messages were sent.

## Reproduction

Run from repository root without putting it in startup PYTHONPATH (legacy sitecustomize):

```sh
OPENBLAS_NUM_THREADS=1 python -m experiments.v265_anatomy.audit /tmp/v265-anatomy-audit
python -m experiments.v265_anatomy.ablation
python -m unittest experiments.v265_anatomy.test_generator -v
```

The audit persists first-failure.npz (exact geometry, expression and invalid triangle
indices), all stress metrics, lineage and provenance before any training admission.
All assets are original analytic code, no imported face models/textures or research
weights. Status ENGINEERING_ONLY; commercial_training_allowed=false.
The6 regression tests validate construction, reproducible negatives, neutral immutability,
root separation and accessory primitives. They are not end-to-end encoder information-
leakage tests, anatomical acceptance, trained identity quality or parser validation.

Next required work: resolve mouth rim/cavity articulation and validate contacts/visibility,
then admit the rendered V4 corpus and StageA training. StageB/C must wait for measured
StageA reconstruction. Existing model contracts and RELIEF-V3 remain frozen.
