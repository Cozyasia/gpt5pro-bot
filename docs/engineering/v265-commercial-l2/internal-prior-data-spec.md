# Internal identity prior: executable pilot specification

2026-09-10. This is a request for a quoted pilot and contractual rights, not an
authorisation to buy data or start full-scale training. FaceVerse rights PENDING.
No new vendor survey. MetaHuman quality remains UNTESTED until access is available.

## Exactly two procurement routes

A. Synthesis AI custom synthetic face dataset: request through
https://synthesis.ai/about/ (Contact Us). Request delivery of persistent neutral
3D meshes and calibrated expression renders, not only face-recognition images.
No public marketing statement is treated as derivative-weight permission.

B. Commission original synthetic 3D identity bases and expression rigs from a
character/scanning studio under an explicit ML-training and derivative-weights
agreement. Generate pose, expression, lighting and camera variations internally.
No standard 3D Scan Store/stock-character purchase is authorised; the earlier
public licence restriction remains applicable. This route is a commissioning
specification, not a claim that a supplier has already granted rights.

Both quotes must identify licensor, underlying mesh/texture sources, contributor
assignments and releases, exclusions and all third-party assets. Require perpetual
worldwide commercial ML training, fine-tuning, optimisation, internal copies,
private container deployment, commercial server inference and proprietary derived
weights; no downstream per-user/request royalties, preferably a fixed pilot and
expansion price. Require surviving rights to trained weights after contract end.
Raw source asset redistribution to users is not required. Permit service providers
and private compute/cloud processing. Require written provenance warranties; a
rendering licence or synthetic appearance alone is insufficient.

## Delivery and quantities

Pilot first: 100 distinct base identities × 12 poses × 8 expressions × 2 lighting
setups = 19,200 renders, plus all 100 neutral meshes and expression displacements.
Withhold 20 entire identities. Pilot acceptance decides expansion, never the toy
harness training score. Supplier must state actual distinct base-identity count;
procedural variants cannot be relabelled as independent scanned people.

Expansion option: 5,000–10,000 persistent synthetic base identities, 12–20 poses,
8–12 expressions. Reference full factorial 5,000×16×10×2 = 1.6 million renders.
Around 100,000 augmented morphology instances may be sampled sparsely with fixed
seeds and lineage; do not order the full factorial of every augmented instance
without a separate compute/storage quote.

Each identity must include neutral canonical geometry, consistent vertex indexing,
metric scale, neutral texture/albedo and expression displacement fields. Deliver
dense native geometry plus barycentric correspondence to Apache-2.0 MediaPipe
468-vertex topology, preserving nose/lips/jaw/chin and eyelids. Retain dense native
meshes so 468 topology is not an irreversible capacity ceiling.

Per render: linear RGB or documented colour encoding (512px or better), albedo,
normals, depth, intrinsic camera K, extrinsic R/t, unit convention, pose, expression
coefficients and displacement, illumination metadata, visible-triangle mask, dense
projected landmarks with visibility and semantic ownership masks. Pose examples:
yaw ±15/30/45 degrees; pitch ±10/20; frontal. Include neutral/closed, broad smile,
open mouth, lip compression, asymmetric corners, eyelid closure and brow changes.

Semantic labels: skin, brows, eyes/eyelids, upper/lower lips, mouth interior/teeth,
hair, glasses frame, transparent lens, opaque lens, neck, background and occlusion.
Do not merge transparent lenses with frames. Include thin/dark/partial frames and
negatives with dark brows, shadows and high contrast. Accessory presence must not
modify neutral geometry or identity labels.

## Machine-readable record contract

Each render record (JSONL) references files with SHA-256:

```json
{
  "identity_id": "base_000001",
  "parent_identity_id": "base_000001",
  "split": "train",
  "variant_seed": 265,
  "neutral_mesh": {"path": "neutral.npz", "sha256": "<64 hex>"},
  "expression_mesh": {"path": "expression.npz", "sha256": "<64 hex>"},
  "rgb": {"path": "rgb.png", "sha256": "<64 hex>"},
  "labels": {"path": "labels.npz", "sha256": "<64 hex>"},
  "camera": {"path": "camera.json", "sha256": "<64 hex>"},
  "rights_agreement_id": "<executed agreement reference>"
}
```

NPZ arrays: vertices float32[N,3], triangles int32[T,3]; labels include depth[H,W],
normals[H,W,3], semantic[H,W], landmarks[468,3], visibility[468], expression[E].
Camera JSON: K[3,3], R[3,3], t[3], units and handedness. Supply topology version and
hash. Keep identity/neutral mesh hash invariant across every scene/expression.
Split by base identity and all its procedural descendants to prevent leakage.

Pilot acceptance: verify all checksums/units, repeated neutral hashes, correspondence
errors, valid nondegenerate topology, silhouette coverage, expression-only deltas,
complete critical labels and an executed rights ledger. Require a neutral/smile
pair per identity and camera reprojection tests. Reject unlicensed asset components
and coefficient labels that bake source smile into neutral identity.

## Real-person data minimisation

Reserve 500–1,000 separately consented real identities chiefly for independent
cross-view validation. Capture neutral frontal/yaw/pitch and neutral/smile pairs.
Keep a sealed identity-disjoint final test subset. Any use for correction/fine-tuning
must be explicitly consented and excluded from that final test. Document permitted
biometric processing, storage/withdrawal, territorial transfers and derived-weight
rights. Synthetic-first is the proposed experiment, not proven domain generalisation.

## Harness and reproduction

`scripts/v265_prior_toy.py` is an original NumPy MLP trained from scratch on Gaussian
point-splat renders of procedural canonical deformations. It uses the checksum-pinned
Apache-2.0 canonical mesh, no person photographs, FaceVerse assets or learned external
weights. Encoder: 24×24 grayscale → 192 tanh hidden units → 128 or 256 bounded
coefficients. Last 32 coefficients decode a separate canonical residual; the remaining
96/224 decode a procedural identity basis. Both bases are projected out of four
explicit **toy** expression modes. These are not validated MediaPipe blendshape
deformations. Target expression/pose enter after identity inference.

Losses: coefficient supervision, topology edge energy and paired-view consistency.
The script logs held-out identity loss, cross-view drift, expression orthogonality,
local residual magnitude and orientation/area diagnostics for one illustrative
neutral held-out render. It does not include a production orientation barrier or
establish case06 validity. Coefficient bounding is not a geometric validity guarantee.

```bash
PROD_HARDENING_ENABLED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python scripts/v265_prior_toy.py --canonical /tmp/v265-canonical.obj --dim 128 --output /tmp/v265-prior128
PROD_HARDENING_ENABLED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python scripts/v265_prior_toy.py --canonical /tmp/v265-canonical.obj --dim 256 --output /tmp/v265-prior256
PROD_HARDENING_ENABLED=0 OPENBLAS_NUM_THREADS=1 python scripts/v265_prior_toy.py --infer-checkpoint /tmp/v265-prior128/toy_checkpoint.npz --output /tmp/v265-prior128/inference.json
PROD_HARDENING_ENABLED=0 OPENBLAS_NUM_THREADS=1 python -m unittest tests.test_v265_prior_toy -v
```

Obtain canonical_face_model.obj from the URL in v265_commercial_assets.json; checksum
is enforced before use. NumPy is the only third-party harness dependency. Raw metrics
are stored beside this specification under internal-prior/. Checkpoints generated by
the commands are disposable toy weights, never production candidates.

Both sizes lower training loss but fail held-out generalisation against zero prior.
Thus memory/output/optimiser wiring is feasible; 128/256 exact-identity capacity is
NOT proven. Procure only the small pilot before selecting backbone or full data scale.
Maintain the 2 GiB full-stack target; isolated toy RSS excludes MediaPipe/parser/app.

## MetaHuman evaluation status (updated 2026-09-10)

Three authorized POST /auth/token attempts returned HTTP 504. Support inquiry sent;
no token or fixture upload. Technical quality UNTESTED. MetaHuman WAITING; FaceVerse
commercial rights PENDING. READY-MADE VENDOR PATH = PENDING / UNQUALIFIED.
See metahuman-registration-attempt.md for the registration evidence.

Internal prior procurement is now ACTIVE independently of these responses.
See pilot-infrastructure-checkpoint.md for RFQ status and executable contract v1.
The earlier illustrative record above is superseded by ingest.py's stricter contract:
raw RGB delivery normalizes to uint8 NPY; dense geometry stays native; correspondence,
expression basis/displacements, rights-ledger binding and lineage are mandatory.
