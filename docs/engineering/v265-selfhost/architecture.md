# FULLY SELF-HOSTED L2 / PROVIDER-INDEPENDENT IDENTITY STACK

Experimental child branch v265-self-hosted-l2, parent PR #119 at
 a50125e58a04cc886dd12c923f9582c2120b1e73. Parent CI10/10 passed. One active owner.
Main c4bda09a98557e1bdea46338bccf66d8b6e6ed61 and Render dep-dafadhdg1s2s73dn3ggg
remain frozen. No production runtime imports, merge, deploy, payments or contracts.

## Executable boundaries

| Layer | Module | Input -> output / version |
|---|---|---|
| Local observations | observations.py | source + pinned MediaPipe task -> landmarks, transforms, expression observations JSON; bootstrap1 |
| Admission | prior/ingest.py + data.py | checksum/rights-bound records -> immutable split records; no mock commercial admission |
| Identity | model.Heads + prior.IdentityEncoder | RGB ->192 intrinsic +32 residual; MobileNetV3-small or ShuffleNetV2 x0.5 |
| Canonical | data.prepare + prior.CanonicalDecoder | TRAIN-only PCA + topology-smoothed residual ->native N×3; separate468 barycentric correspondence |
| Expression | decoder expression basis | canonical + independent expression coefficients ->expressed native mesh |
| Camera/supervision | geometry.py | metric K/R/t ->projected vertices, soft silhouette/depth visibility; geometry1 |
| Appearance | model.Heads.albedo | source coefficients ->canonical albedo UV; target illumination separate |
| Parsing | model.Heads.parsing | source RGB ->15-class logits; depthwise15-v1; not ownership-qualified |
| Render | geometry.raster/composite | validated geometry +UV/albedo +camera +ownership ->PNG pixels; geometry1 |
| Quality | gate.py | morphology/cross-view/expression/geometry/visibility/accessory/appearance evidence ->fail-closed report |
| Worker | worker.py | hashed local job +model manifest ->canonical NPZ, diagnostics, semantic logits, PNG; worker1 |

No user face image requires an external inference API. Generic compute rental for
training or our own worker hosting is allowed; it is not an external face service.
FaceVerse/MetaHuman remain optional accelerators/reference. No fallback/rescue path.

## Full real-record training chain

`data.prepare` builds neutral PCA ONLY from train identities. Shared expression
basis and dense native topology are checked. Topology-smoothed original residual
basis is spatially attenuated in expression-sensitive regions, then projected away
from expression span. Sum-of-basis local bound guarantees <=1.5mm residual for bounded
codes. This is algebraic separation, not proof of real smile/identity disentanglement.
Native vertices are unrestricted above468. Mock uses520, not an anatomical face model.

`trainer.run` admission ->paired loader ->heads ->canonical/expression ->calibrated
projection/soft visibility ->actual record masks/depth/landmarks/albedo/semantics ->
optimizer ->held-out validation ->checkpoint save/load(weights_only) ->ONNX ->native
comparison. No manual conversion between those stages. External supplier format must
conform to the versioned ingest contract; v1 requires common expression basis and UV.
Native albedo is preserved; v1 appearance head supervises a deterministic16×16 UV
view. This is a functional low-resolution baseline, not exact skin-detail capacity.

Every loss has explicit weight: neutral/coefficients/residual, paired identity,
expression orthogonality, silhouette/visibility/depth/landmarks, seven facial groups,
orientation/log barrier, edge/area, compression/expansion, Laplacian and ARAP-like
Gram metric, residual bound, albedo and semantic CE. Nonfinite loss/gradient fails.
No full ARAP local-rotation solver is claimed. Batch1 uses frozen BN statistics.
Two backbones share decoder and evaluation; no quality winner selected.

Soft visibility uses triangle signed-edge distances and soft depth ordering; it is
piecewise differentiable and approximate at discrete visibility transitions. Hard
inference uses deterministic pixel centers, z-buffer, perspective barycentrics,
bilinear UV and stable triangle-ID ties. Geometry validation precedes raster.
Edge-on projected triangles have zero coverage; invalid canonical triangles reject.
Raster is deliberately two-sided; back-facing counts are logged. Closed-surface
backface semantics and large pose/silhouette quality still need real topology data.

## Worker and product invariants

The local file API accepts only schema_version/job_id/source/target/model_manifest_sha256.
Source and target assets carry SHA-256. Target NPZ contains K/R/t, expression, scene,
support/protected/neck/occlusion masks and optional illumination. Target image NEVER
enters the identity encoder. Model and canonical hashes are checked; same source
inference must be bit-exact on repeat. TEST ONLY artifacts require diagnostic mode.

PERSON-B, neck and explicit occlusion pixels are copied bit-exact. Feather cannot
expand support. Albedo follows geometry; illumination is a separate bounded normal
field. Source semantic logits are diagnostic until independently qualified; caller
ownership masks require trusted annotations. No autonomous product ownership claim.
Gate denies missing evidence and all mock weights. PNG remains an original document
artifact; no Telegram delivery wired. Human approval remains necessary.

Future deployment: Telegram bot ->durable queue ->local preprocessing ->identity
worker ->render worker ->local gate ->PNG/document sender. Versioned model storage
is content-addressed; job retains model/config/source/target hashes and renderer
version. Bot need not hold torch/MediaPipe. Worker is executable without bot. Queue,
service deployment, authentication/retention controls and human-approved delivery
adapter are future infrastructure tasks, not deployed by this PR.

## Curriculum and independent evaluation

curriculum.py defines A neutral; B paired cross-view; C expression; D albedo; E
accessories; F full render. Each stage lists machine criteria. Exits require approved
validation calibration with provenance. No loss-only advancement; thresholds not
invented from mock. ENGINEERING_ALL_LOSSES is restricted to mock. Quality stages
remain unpassed. Stage criteria include mouth proportions/opening/smile/teeth,
critical holes, contour, orientation, accessories and person-B/neck locks.

Cross-view infer-once contract is reused. Independent B annotations supply controls
and ground truth; no fit of candidate to B. Same-photo does not qualify. Tests reject
identity mismatch and verify target does not mutate canonical identity. Existing
cases01/02/04/05/06/07/08 and photo3 negative evidence remain unchanged. Mock analogues
exercise contracts only; they do not requalify case06/07/08 or photo3.

## Provenance

model-manifest.json: architecture, code commit and source digest, exact dataset and
rights ledger hashes, training config/seed, parent checkpoint SHA, validation metrics,
ONNX/checkpoint/canonical SHA, topology/expression/parsing/renderer versions and
commercial_training_allowed/mock_only flags. Flags record legal approval; they do
not replace review of the executed agreement. No real approved rights ledger exists.

## Procurement and external status

MetaHuman WAITING/UNTESTED; FaceVerse rights PENDING; Synthesis AI/Carahsoft first RFQ
SENT, no follow-up today. Ready-made vendor route PENDING / UNQUALIFIED.
One second non-binding RFQ SENT to contact@3d-ace.com, subject:
Non-binding RFQ: commissioned original synthetic 3D identities for ML pilot.
Official contact: https://3d-ace.com/contact-us/
Capability: https://3d-ace.com/3d-modeling/3d-character-modeling/
Facial rigging: https://3d-ace.com/tech-expertise/
Asked for100 original identities, separate geometry/rig-only and19,200 calibrated
render quotes, persistent dense neutral/UV, expression fields, labels including
frames/lenses/occlusion, ML/derivative/perpetual/server/private-cloud rights,
provenance and no per-request royalties. No paid obligations. Price/rights UNKNOWN.
No response known at initial check. Supplier capability/rights not yet qualified.

## Reproduction

```bash
python -m venv /tmp/l2env
/tmp/l2env/bin/pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu
/tmp/l2env/bin/pip install -r experiments/v265_prior/requirements.txt
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 /tmp/l2env/bin/python -m unittest experiments.v265_selfhost.test_stack -v
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 /tmp/l2env/bin/python -m experiments.v265_selfhost.dryrun /tmp/l2-dryrun
# Real isolated Docker path (build network for generic packages; run network disabled):
docker build --build-arg CODE_COMMIT=$(git rev-parse HEAD) -t v265-selfhost -f experiments/v265_selfhost/Dockerfile .
docker run --rm --network none --memory=2g --memory-swap=2g --cpus=2 -v /tmp/l2-results:/results v265-selfhost
```

Mock is6 identities×2poses×2expressions×2lighting=48records, structurally identical
extended records with three splits. This is a reduced engineering dry-run, not the
100-identity19,200-render supplier pilot. Identity-generalisation conclusions forbidden.

## Fastest path and limits

Implemented now: admission, dense interfaces, two heads/backbones, train-derived
basis, expression/residual math, differentiable supervised geometry, own albedo and
parsing heads, trainer/save/load/export, cross-view harness, local worker/raster/gate.
Software follow-ups: high-resolution efficient differentiable raster, stronger
appearance decoder, anatomical expression semantics, service queue and delivery.
Blocked by pilot/rights: identity prior quality/generalisation, anatomical capacity,
real case06/08 selection, commercial trained weights. Human labels needed: sealed
cross-view data, case07 masks, smile/teeth and identity acceptance calibration.
GPU: no hardware available here; CPU dry-run is executable, no GPU throughput or
VRAM result is invented. Real pilot training likely requires generic GPU compute;
procurement and hardware provisioning require separate approval before spending.

2GiB/4GiB CI runs use Docker memory+swap limits and network=none. Shared scratch
cgroup is read-only; local memory measurements cannot qualify an isolated limit.
Full mock CI does not include production Telegram daemon or real-quality dense models.
GPU operating-cost reference only: Runpod A4000 Secure Cloud advertised from$0.25/h
(~$182.50/730h before storage/network) on2026-09-10; no instance purchased.
https://www.runpod.io/gpu-models/rtx-a4000
CPU prices must be confirmed against https://render.com/pricing; no deployment chosen.

SELF-HOSTED L2 MVP remains NO: no real identity weights or public-matrix machine
prequalification. Infrastructure execution PASS is not full L2 identity acceptance.
