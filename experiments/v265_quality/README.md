# SELF-HOSTED L2 QUALITY TRACK — original procedural experiment

Owner PR #120; parent #119 retains all negative real fixtures. No production changes.
Existing module contracts remain the architecture baseline.

## Scope and provenance
`factory.py` is original analytic code: no external head/identity/texture model,
no dataset, no trained weights. Seed 265120 fixes 128 identities × 8 views (1,024
records), 80 train / 24 validation / 24 test. Identity IDs and hashes are checked
before training. Rights status is ENGINEERING_PRETRAINING_ONLY and explicitly
`commercial_training_allowed=false`. This experiment has a dedicated loader; it
DOES NOT bypass the commercial admission ledger of the existing pilot trainer.

Two native grids: 2,009 / 5,265 vertices. The shape contains analytic orbital,
nasal, lip, philtrum, cheek and jaw relief. It is an OPEN FACIAL PATCH, not a full
anatomical head. Lip ridges do not provide separate closed-mouth cavity topology;
nostril relief does not constitute volumetric nasal anatomy. Accessories are
surface texture decals, not independent physical frames/lenses. Hair, teeth,
mouth interior, neck and generic occlusion are NOT modelled. The 15-output parsing
head cannot claim supervision for absent classes. These are known capacity gaps,
not anatomical or real case06/07/08 acceptance.

Semantic IDs: background0, skin1, brows2, eyes3, eyelids4, upper_lip5,
lower_lip6, mouth_interior7, teeth8, hair9, glasses_frame10,
transparent_lens11, opaque_lens12, neck13, occlusion14. This experiment's explicit
mapping must be translated by name before any use with the prior admission schema.

Identity = 24 anatomy controls plus 12 original bounded residual modes.
Expression = 8 separate displacement modes, applied after immutable identity.
Residual modes are orthogonal to the expression span. This algebra does NOT
prove image encoder disentanglement. Training views intentionally include
combined nuisance changes; combined drift is not mislabeled expression-only drift.

## Versioned experiment commands
Run from repository root, with torch2.5.1, torchvision0.20.1, numpy1.26.4,
Pillow, scipy, onnx1.17.0, onnxruntime1.20.1. No pretrained downloads.

```sh
python -m experiments.v265_quality.factory /data/procedural --identities 128
python -m experiments.v265_quality.geometry_audit /data/topology.json
python -m experiments.v265_quality.train /data/procedural /data/mobile128 --epochs 12
python -m experiments.v265_quality.train /data/procedural /data/shuffle128 --backbone shufflenet_v2_x0_5 --epochs 12
python -m experiments.v265_quality.train /data/procedural /data/mobile256 --latent 256 --epochs 12
python -m experiments.v265_quality.train /data/procedural /data/learned256 --latent 256 --representation learned --uv-size 128 --epochs 12
```

Fixed budget, deterministic seed, validation-only checkpoint selection; sealed
identity test evaluated once per predefined configuration. Final backbone ranking
must consider geometry and invariance, not training loss. The fourth run changes
both representation and UV resolution and therefore cannot isolate UV resolution's
causal quality effect. Native training, heldout evaluation, reload, ONNX export,
parity, weights/model/dataset hashes and loss weights are written in report.json.
No V0 can be declared from reconstruction improvement alone: current full-surface
and intrinsic-mouth tests remain unqualified. No real public matrix or human sheet
until V0's complete contract passes.

## Real pilot remains gated
PRETRAIN on this original corpus; FINETUNE on licensed anatomical pilot after
executed agreement/legal review, admission and identity-disjoint audit. Do not
replace existing supplier RFQ or reduce it before supplier response. Existing
commercial trainer/curriculum must not accept this experiment's TEST_ONLY ledger.
