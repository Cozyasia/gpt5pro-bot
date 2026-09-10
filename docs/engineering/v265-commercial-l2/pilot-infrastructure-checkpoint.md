# Internal prior pilot infrastructure — 2026-09-10

Parent PR #119: fd9693db0a17925432cfce7b34fbb6fd37942da3. Local work moved to
v265-pilot-infrastructure directly from the published PR branch. Old local
v265-internal-prior retained. Changes will be published into #119, not main.
Production remains frozen on c4bda09a98557e1bdea46338bccf66d8b6e6ed61.

## Procurement is active

READY-MADE VENDOR PATH = PENDING / UNQUALIFIED. MetaHuman WAITING; previous three
POST attempts returned 504. No new registration, token, photograph upload or support
follow-up. FaceVerse rights PENDING; no additional licensing action. Latest mailbox
check found no incoming MetaHuman/FaceVerse/Synthesis reply.

Non-binding RFQ SENT to SynthesisAI@carahsoft.com, the named Synthesis AI team on
https://www.carahsoft.com/synthesis-ai (Contact Us, independently verified). The
Synthesis AI direct https://synthesis.ai/about/ contact page returned 502 from this
environment; no email address was guessed. This is the Synthesis AI partner route,
not a claim that Synthesis AI enterprise has already acknowledged receipt.

Subject: Non-binding Synthesis AI RFQ: 100 synthetic identities / 19,200 calibrated face renders.
Requested routing to Synthesis AI enterprise if this team cannot serve a commercial
customer in Thailand. Included 100×12×8×2 renders; neutral dense meshes, persistent
identities, expression displacements, calibrated K/R/t, depth/normals/visibility,
separate accessory labels, commercial ML and derivative-weight rights, worldwide
paid server inference, surviving trained-weight rights, no per-request royalties,
provenance, price, lead time and sample availability. No attachments, photos,
secrets, purchase, payment or acceptance of terms. Quotation UNKNOWN; rights PENDING.
Route B supplier specification prepared separately; not sent.

## Executable admission contract

`python -m experiments.v265_prior.ingest DATA_ROOT --pilot`

Commercial mode is the default. Missing/unchecked rights cannot enter training.
JSONL fields and NPZ array names are executable in ingest.py, with an original
procedural sample generator in tests/test_v265_pilot.py. This is normalized ingest
format, not an assumption that every supplier natively returns NumPy files.

- Every referenced file: relative confined path, SHA-256, size limit, no pickle.
- Record IDs; identity/root lineage, split, pose/expression/lighting IDs; units m;
  pinned common dense topology hash/version, valid indices/nondegenerate triangles,
  no duplicate faces or >2 incident triangles per edge; neutral invariance.
- Native N>=468 has no 468 upper bound. Barycentric 468 correspondence remains
  separate. Metric vertices; expression basis and exact displacement consistency.
- uint8 RGB NPY; NPZ metric depth, unit normals, semantic enum, pixel/landmark/triangle
  visibility; critical native region groups; K/R/t with proper right-handed rotation.
- Rights ledger binds exact manifest SHA; executed document SHA, licensor, approved
  reviewer, every requested grant and no unresolved restrictions. This records a
  human legal review; it cannot authenticate a signature or infer rights from flags.
  No real approved ledger has been created in this cycle.
- Resolve every ancestor; reject missing parents/cycles and descendants crossing
  splits. Reject duplicate neutral/RGB hashes across splits; rigid-aligned native
  mesh RMS <=0.1mm is a conservative near-duplicate screen, not perceptual proof.
  Supplier lineage/provenance review remains required for remeshed/unreported copies.
- --pilot checks 100 identities / 19,200 records, all three splits and complete unique
  12×8×2 combinations per identity. Split assignment is supplier/ingest metadata;
  the validator rejects leakage, it does not silently repair/reassign approved data.

--smoke admits ONLY explicitly original procedural smoke records and always emits
commercial_training_allowed=false. Training Dataset calls admission before loading
images and rechecks each opened asset hash. Identity-paired reads stay within split.
Data must be stored immutably after admission; training must retain ledger/manifest
hashes. No commercial training is run here.

## Training scaffold and cross-view contract

RGB encoder -> 192 intrinsic coefficients +32 residual coefficients. Constructor
supports different dimensions; no capacity choice based on smoke accuracy.
Decoder consumes dense neutral/identity/residual/expression bases. Identity/residual
bases project away from the expression span using rank-aware SVD. Canonical output
is immutable with respect to target pose/expression; those controls apply afterwards.
Dense decoder tested at 620 vertices, separate barycentric 468 output tested.

Bases must be built from approved TRAIN identities only. This cycle supplies neither
a learned identity basis nor pilot-trained weights. Algebraic expression orthogonality
is implemented, but semantic smile/identity separation is unproven.

Mandatory loss interfaces: neutral, coefficients, residual, paired-view consistency,
expression orthogonality, silhouette, landmarks, weighted jaw/chin/nose/mouth/eyes/
cheeks/brows, orientation penalty, edge/area, uniform graph Laplacian and per-triangle
Gram/ARAP-like metric penalty. Every loss needs an explicit weight. Nonfinite loss or
gradients reject. Full local-rotation ARAP solver is not claimed. Differentiable
silhouette/projection adapter remains a future geometry component; smoke stand-ins
only exercise the interface. No renderer has been added.

`evaluate.cross_view_protocol` calls an A-only identity inference callable once, then
projects the same immutable canonical identity into each B pose/expression. It checks
same identity, different source bytes and held-out split. Outputs regional canonical
RMSE, withheld projected NME, corresponded visible silhouette NME, mouth intrinsic
ratios and opening/corner errors. Target photos cannot enter the encoder through this
interface. Inputs B geometry/controls must be independent annotations, not another fit
of the candidate. CLI evaluates saved geometry pairs without optimisation.

Case06: area/edge/aspect distributions and orientation count; calibrated validation
limits required. Full PASS additionally requires supplied independent critical
coverage masks (zero holes), never culling. Case08: source-neutral width/lip/philtrum/
nose/chin errors and target opening/corners, independently measured smile/teeth;
complete calibrated thresholds required. Missing coverage, smile/teeth, or calibration
keeps results UNQUALIFIED. Neither case has been run with learned internal weights.
No calibration on case06/08; no fidelity-gate tuning; no human sheet.

## Reproduction and engineering results

Python3.12, CPU only, one compute thread, random seed265, random RGB224×224, batch1.
No pretrained torchvision weights are downloaded (weights=None).

```bash
python -m venv /tmp/v265-training-env
/tmp/v265-training-env/bin/pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu
/tmp/v265-training-env/bin/pip install -r experiments/v265_prior/requirements.txt
PROD_HARDENING_ENABLED=0 /tmp/v265-training-env/bin/python -m unittest tests.test_v265_pilot tests.test_v265_prior_model -v
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 /tmp/v265-training-env/bin/python -m experiments.v265_prior.benchmark --output /tmp/v265-pilot-benchmark
```

| Encoder | Params | Parameter MiB | Native p50 ms | ONNX p50 ms | ONNX peak RSS MiB |
|---|---:|---:|---:|---:|---:|
| MobileNetV3-small features | 1,056,256 | 4.03 | 5.14 | 1.83 | 68.28 |
| ShuffleNetV2 x0.5 features | 571,392 | 2.18 | 8.70 | 1.43 | 65.40 |

Both export opset17; compare ONNX output to the same native model (max error<1e-5).
Both complete two smoke optimizer steps with finite gradients. This is not a training
convergence/generalisation or exact-identity benchmark. Backbone winner deferred.
Native fresh inference peaks333.70/329.27MiB; native two-step training395.17/376.22MiB.
Export memory is separately recorded and excluded from inference qualification.

Torchvision source/docs:
https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.mobilenet_v3_small.html
https://github.com/pytorch/vision/blob/main/torchvision/models/shufflenetv2.py
ONNX session/thread documentation: https://onnxruntime.ai/docs/performance/tune-performance/threading.html

## Lifecycle and memory bounds

Additional measured local run: MediaPipe0.10.21, checksum-pinned existing assets,
public frozen case02 source, one face detected. No external image transmission.

- Imported MediaPipe + ORT frameworks: see lifecycle.json.
- Landmarker + MobileNet ONNX: current RSS257.71MiB.
- After closing fit/encoder and trim:209.92MiB.
- Sequential parsing current RSS413.66MiB, peak412.63MiB.

Current RSS comes from /proc/self/status. psutil PID lookup was unsuitable in this
nested namespace; resource peak and current readings may differ slightly due to
sampling/accounting. Raw current/peak/cgroup/file-cache records are retained.
Host cgroup is shared (~14GiB limit); its usage is NOT an isolated worker measurement
and this run did not enforce2GiB. Do not subtract shared cache to claim qualification.

Warmed app planning estimate ONLY: allocate ~0.41GiB observed isolated worker +
0.5GiB allowance for warmed app/legacy residency +0.12GiB dense bases/solver/buffers
(10k vertices, 192+32+52 FP32 modes ~31.6MiB before temporaries) +0.25GiB operational
margin ~=1.28GiB. These allowances are not new measured application residency.
2GiB remains the candidate tier. Full app+worker cgroup, production concurrency,
real fitted geometry and pilot image sizes still require actual measurement.
512MiB and1GiB are NOT qualified; 2GiB is a design target, not a deployment verdict.

Optional lifecycle reproduction (model URLs/hashes already in commercial asset manifest):
```bash
/tmp/v265-training-env/bin/pip install mediapipe==0.10.21
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 /tmp/v265-training-env/bin/python -m experiments.v265_prior.lifecycle /tmp/v265-pilot-assets /tmp/v265-pilot-benchmark/mobilenet_v3_small.onnx /tmp/v265-pilot-benchmark/lifecycle.json
```

CI adds offline admission, dense decoder/loss tests and both fresh-process encoder
benchmarks. No supplier/token/download-registration/FaceVerse assets in this new job.
Infrastructure ready to receive/validate pilot data; actual rights/data, approved
training-derived bases, independent labels/calibration and full trainer supervision
adapter remain prerequisites to a quality model. Full L2 implementation NOT ready.
