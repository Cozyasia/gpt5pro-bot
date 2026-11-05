# V265 commercial identity procurement checkpoint

Date: 2026-09-09. Scope: identity geometry only. Production remains frozen.
FaceVerse commercial rights are pending and its research assets remain prohibited
from CI, deployment and production.

## Decision table

| Candidate | Public technical capability | Public commercial/server verdict | Can benchmark now? | Decision |
|---|---|---|---|---|
| MetaHumanSDK.io 3D Face Reconstruction | Hosted POST API returns 80 shape coefficients and UV texture; GLB constructor returns a 5,255-vertex head with ARKit blendshapes | **UNCLEAR.** Documentation proves unattended server calls, but no public price, SLA/rate limit, DPA, photo retention/deletion, training-on-input policy, output ownership or grant for paid SaaS was found. This is not Epic's MetaHuman license. | No authorised token/terms | Primary Track-B trial, conditional on written answers below |
| Banuba Face AR SDK | On-device face tracking/AR; public product matrix lists Android/iOS/Web/macOS/Windows/Unity, not Linux server; public material describes a 3,308-vertex AR mesh | **NO for the current server identity-base requirement under public terms.** Rights exist only through a signed Order Form. Public material does not promise intrinsic identity/expression coefficients, exportable canonical geometry or Linux server automation. | 14-day token is available, but it would test a client tracker, not the required identity prior | Do not spend benchmark time unless Banuba confirms a server build and export rights in the Order Form |
| Internal MediaPipe-topology prior | We own training and runtime; MediaPipe topology/expression foundation is Apache-2.0 | **Potentially clear only after training-data contracts.** No listed dataset is assumed usable from marketing language alone. | Harness and topology exist; training assets do not | Fallback with synthetic-first procurement |

Banuba's SDK processes frames locally and states that images are not sent to its
servers. That is privacy-positive for supported clients, but does not create a
server-side reconstruction service. Its public pricing is custom and depends on
platforms/features/MAU; a 14-day trial is public. The licensing terms bind only
through the Order Form, define Product platforms, and forbid ungranted
distribution/modification. Therefore an Account Manager statement is not enough:
the required deviations must appear in the Order Form.

## MetaHumanSDK.io request (send through its token/support contact)

This request is for **metahumansdk.io**, not Epic Games MetaHuman:

> We operate a paid Telegram/SaaS service that performs unattended server-side
> reconstruction of user-supplied photographs. Please provide a trial token and
> the controlling Terms, commercial Order Form and DPA. Confirm in writing: (1)
> worldwide commercial server/API inference at our expected monthly request tier;
> (2) price, minimum term, rate/concurrency limits, latency/SLA and geographic
> endpoint/cloud region; (3) our perpetual right to store, modify and use returned
> blendshapes, 5,255-vertex GLB geometry, texture and derived canonical identity
> coefficients in a proprietary renderer; (4) ownership of outputs and whether
> they may train our own non-competing identity model; (5) no vendor training or
> human review of input photos without opt-in; (6) exact input/output/log retention,
> immediate deletion API and deletion SLA; (7) DPA roles, biometric-data terms,
> subprocessors, transfer mechanism and security incident terms; (8) arbitrary
> consenting adult user photos, including public figures, are permitted; and (9)
> the licence covers automated production and benchmark requests rather than only
> demonstration use. Please identify any prohibited territories or image classes.

Blocking answers: paid SaaS use, server automation, output/derivative ownership,
photo retention/training, DPA/biometric terms and benchmark permission. Public docs
only establish the API shape, 10 MB input limit, token auth, 80 coefficients,
texture URL and 5,255-vertex GLB/ARKit output.

## Banuba Order Form request

Submit the Face AR SDK free-trial form, then require this language in the Order
Form before evaluation with frozen photos:

> Product is a paid Telegram/SaaS bot running unattended on Linux servers, not a
> mobile end-user SDK. Confirm delivery/support of a Linux x86-64 server library or
> hosted API; arbitrary-volume still-photo processing; export and perpetual use of
> per-user canonical mesh, intrinsic identity coefficients and expression
> coefficients; use of those outputs in our proprietary renderer; no restriction
> to transient AR effects; and no Banuba claim over customer inputs or outputs.
> State platforms, MAU/request metric, price, trial scope, concurrency, SLA and
> territories. Confirm on-device/local processing semantics for our server, no
> photo upload to Banuba, analytics fields and disablement, DPA controller/processor
> roles, biometric-data treatment, subprocessors, regions, deletion and audit
> rights. Confirm that our benchmark exports may be retained after trial expiry.

If Banuba will not put server delivery plus canonical-output rights in the Order
Form, it is disqualified without a technical benchmark.

## Vendor export benchmark contract

`v265_vendor_identity.py` and `v265_vendor_identity_benchmark.py` accept authorised
offline exports only. They load no token and make no network request. Every frozen
case must provide separately addressable intrinsic identity and expression,
dense topology, source hash and canonical geometry metadata. The gate also requires
identical identity hashes for repeated-source pairs 01/05 and 02/06. Geometry
metrics for case06 and expression metrics for case08 run only after all seven
exports are present. Current status: zero authorised exports, so VENDOR BENCHMARKED
= NO; no synthetic score is substituted.

## Training-data procurement

| Source | What is actually available | Rights status for our derivative weights | Procurement requirement |
|---|---|---|---|
| Synthesis AI custom face data | Commercial vendor advertises millions of controllable synthetic identities and pixel-perfect 3D labels | Not publicly granted at asset/weight level | Contract for 5–10k persistent 3D identities, neutral mesh + 8–12 expressions + 12–20 poses, unrestricted commercial derivative weights, no royalty/MAU, perpetual internal copies, provenance warranty |
| 3D Scan Store / Ten24 custom or Metamorph assets | High-resolution heads and explicit paid R&D/commercial tiers | **Public licence is insufficient:** it expressly bars selling/distributing digital humans made from AI-training derivatives; ordinary R&D/commercial tiers do not grant our model use | Ask for a bespoke ML-training amendment covering derivative weights and production inference; otherwise exclude |
| Commissioned capture partner | Newly consented scans under our specification | Clear only with participant releases and vendor assignment | 500–1,000 real identities for withheld cross-view validation; explicit biometric consent, worldwide commercial ML training, derivative weights, deletion/withdrawal process, no royalties |

Public Microsoft FaceSynthetics is excluded because it is non-commercial. Public
FaceVerse datasets/assets remain research-only pending a separate grant. A vendor's
claim of “privacy-compliant synthetic data” is not a licence; procurement must
include source-asset provenance and a warranty that the vendor may license the
delivered meshes, textures and labels for derivative-model training.

### Synthetic-first feasibility

The practical route is 5–10k contractually licensed persistent base heads, expanded
procedurally to roughly 100k identity instances while keeping identity labels
stable. For each identity render neutral plus controlled expressions, yaw/pitch,
camera, illumination, skin detail and accessories. Train 128–256 intrinsic
coefficients plus an expression-orthogonal residual on MediaPipe topology; reserve
the commissioned real scans only for cross-view validation and small domain-gap
fine tuning. This meets the numerical data target without scraping biometric
photos, but only after a contract grants derivative weights and provenance.

## Ranked path

1. MetaHumanSDK.io signed trial: shortest route to an actual server-side dense
   export; proceed only if terms cover user photos and output/derivative rights.
2. Internal MediaPipe-topology identity prior using synthetic-first contracted data:
   slower, but gives durable ownership and exact identity/expression objectives.
3. Banuba only if its Order Form unexpectedly grants Linux server operation and
   canonical export; current public product is a client AR tracker, so it is not a
   presumptive identity solution.

FaceVerse moves to rank 1 if the pending commercial grant covers the exact weights,
assets and service use and its constrained residual subsequently passes case06/08.

## Memory qualification target

No remote vendor inference was run. MetaHumanSDK.io would remove the identity
regressor from local RSS but add network/privacy/SLA dependency; normalization of a
5,255-vertex GLB is negligible beside the measured 749,552 KiB MediaPipe+parser
lifecycle. The current local stack fails 512 MiB, fits 1 GiB only as an isolated
worker with insufficient warmed-app margin, and is designed for a 2 GiB candidate.
An internal prior is budgeted under the same 2 GiB target until measured end-to-end.

