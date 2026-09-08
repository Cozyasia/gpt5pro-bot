# L: canonical decomposition prequalification, not a working compositor

Production frozen. I/K retained as negative references. No generated output has
human production approval. This directory contains public-fixture scalars only.

## Root cause and scope

`v265_shape_lab.orthographic_projected_source` fixes every source vertex depth to
the generic template, solves XY to reproduce observed source landmarks, then
projects the result with target camera parameters. Observed source expression,
projection ambiguity and silhouette correspondence therefore survive in the
transported coordinates. `expression_mouth` is a bounded 2D adjustment; it does
not neutralize source appearance. The compositor transfers source pixels,
including teeth, lip expression and glasses; accessories have no separate owner.
The current V265 Stage-1 prompt explicitly locks source smile, mouth opening,
teeth visibility and squint. The new target-expression contract also requires a
future prompt change; production prompt remains frozen. Case05/06/07/08 are
consistent with these limitations. They do not prove one
single cause for every visible defect: TPS boundary inconsistency was separate.

## Implemented architectural experiment

L uses a 3DDFA V2 MobileNet x0.5 regressor, exported to ONNX, with a learned 3DMM:
38,365 vertices, 76,073 triangles, 40 identity and 10 expression parameters.
Final geometry is mean + identity_basis * source_identity + expression_basis *
target_expression, projected using target's estimated affine camera.
Source expression/camera and target identity have no algebraic path into that
construction. There is no appended 2D residual and no coefficient search.

This is an estimated factorization, not proven disentangled identity. It is not
a full perspective/articulated-jaw reconstruction. MediaPipe mesh/transform and
blendshape classifications do not themselves supply neutral personal geometry.
DECA/EMOCA are heavier research alternatives, with separate model restrictions.
BFM commercial asset clearance is unverified; upstream MIT code licensing does
not establish commercial rights for the face model. No weights are committed.

## Seven-case results

All seven parameter/mesh evaluations completed locally. Five source caches;
case01/05 and case02/06 have identical source identity digests by construction.
This proves target independence of the cache, not invariance across distinct
photographs of the same person.

Independent PIPNet source-to-3DMM chin errors: case01 .1131; case02 .0852;
case04 .1146; case05 .1131; case06 .0852; case07 .1730; case08 .1167.
These source reconstruction errors already block exact-source fidelity.

Same-camera projected triangle orientation changes: 131 / 518 / 205 / 217 /
665 / 285 / 393 for case01/02/04/05/06/07/08. All have zero 3D normal reversals.
IMPORTANT: projected sign changes near the silhouette are not automatically
3D mesh foldovers; they can mark changed visibility. A 2D inverse compositor
cannot consume them as ordinary correspondences. Visibility-aware rasterization
and disocclusion remain unresolved. No count is relabeled as successful renders.

Source identity and target expression coefficients are retained exactly, but
that is an algebraic invariant, not a measured expression/identity success.
Case08 mouth texture still requires handling teeth/lips/disocclusion; coefficient
replacement alone cannot prove that a broad source smile is absent in the image.
Case07 has no verified accessory segmentation; protecting all eye pixels would
leave target eye identity and would not satisfy the requirement.

`require_renderable` blocks invalid geometry or missing accessory, visibility and
mouth texture evidence. It is infrastructure, not an implemented segmentation or
appearance generator. **L is a decomposition prototype, not yet a working image
generator. No new human sheet is warranted.**

## Memory and reproducibility

ONNX regressor: 3,389,923 bytes. Canonical arrays: 24,392,528 bytes.
Isolated initial decomposition run peaked at 278.0 MiB; adding independent
PIPNet measurements peaked at 472.0 MiB on an unconstrained local process.
These are not full daemon or production compositor qualifications.

Reproduce assets with `scripts.v265_canonical_prepare` (export-only Torch CPU,
ONNX; pinned SHA256 downloads; restricted array unpickling). It verifies ONNX
versus Torch and OpenCV DNN output parity. Runtime uses the existing OpenCV DNN,
imports neither Torch nor ONNX Runtime. The initial container attempt failed on
missing ONNX Runtime before inference; it was not an OOM. Then run
`scripts.v265_canonical_matrix` with the existing frozen fixture manifest.
The dedicated workflow executes inside 512 MiB and holds L components alongside
the constructed application and warmed PIPNet/MobileFace during baseline
standard/strict. That is a component budget test, not a finished L render or live
Telegram daemon history qualification.

Tests enforce factorization, inverted/collapsed/excessive mesh rejection, missing
semantic-evidence rejection, all fixture hashes and exact repeated source bytes.
The previous interrupted local environment's full suite did not pass (7 failures,
1 error); that result must not be represented as green. Fresh CI is authoritative.
