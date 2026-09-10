# Commercial L2 replacement checkpoint

Date: 2026-09-09. Experimental only; no production import, merge or deployment.

## Decision

Three practical routes were checked rather than starting another broad model survey.

| Route | Asset/right status | Identity capacity | Decision |
|---|---|---|---|
| MediaPipe Face Mesh + non-learned canonical residual | Face Mesh model card and repository assets Apache-2.0 | Dense observed surface but no learned intrinsic identity prior | Implemented as L2-C capability test; rejected as complete identity base |
| MetaHuman SDK 3D Face Reconstruction service | Commercial API/token route; weights stay vendor-side | Returns texture and 80 shape blendshapes | Not selected: no local weights, unresolved user-photo/DPA/terms, neutral-input limitation |
| Banuba Face AR SDK | Public commercial Order Form route | Tracking/AR SDK; exact source-identity reconstruction not established | Not selected without contract and technical proof |

No public self-hosted pretrained identity model was found with all four independently clear layers: code, weights, commercial server inference and training-derived provenance. The selected production direction is therefore an internally trained/licensed identity prior over the Apache MediaPipe topology, with the non-learned residual retained as a bounded detail layer.

## Implemented L2-C result

The prototype uses 468 Apache MediaPipe vertices and 898 canonical triangles. Source pose is removed by rigid similarity alignment. A fixed geometric expression subspace covers mouth opening/smile/compression/protrusion, eyelids and brows. Stored identity residual is projected exactly orthogonal to that subspace and bounded to 0.18 canonical interocular distance. Only target expression coefficients and target pose are reapplied.

Repeated source identity hashes are bit-identical for case01/case05 and case02/case06.

| Case | Self RMSE/IOD | Orientation failures | Area ratio | Edge stretch | Mouth width err | Philtrum err | Mouth/chin err | Target opening err |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 01 | .0046 | 51 | .131–4.976 | .131–3.734 | .168 | .012 | .105 | .002 |
| 02 | .0144 | 21 | .353–10.514 | .245–3.393 | .158 | .008 | .175 | .012 |
| 04 | .0366 | 17 | .051–4.559 | .057–3.875 | .070 | .007 | .298 | .014 |
| 05 | .0046 | 30 | .088–3.479 | .111–2.210 | .026 | .001 | .058 | .006 |
| 06 | .0144 | 52 | .112–16.210 | .167–5.193 | .135 | .007 | .184 | .005 |
| 07 | .0180 | 18 | .105–2.371 | .140–2.465 | .024 | .002 | .094 | .001 |
| 08 | .0246 | 14 | .087–1.467 | .127–1.403 | .019 | .042 | .133 | .033 |

This is not close enough to the FaceVerse research reference. Case06 is substantially worse than FaceVerse+residual (1 orientation failure, area maximum 5.932, edge stretch 2.150). Case08 improves the previous FaceVerse mouth/chin error from .531 to .133 and philtrum from .0668 to .0415, but target opening still misses by .0328 and intrinsic relations fail. Same-photo self reconstruction is not an independent cross-view proof.

Conclusion: non-learned MediaPipe residual is useful evidence and legally clean, but cannot replace a rich identity base. No renderer was built.

## Commercial parsing

The Apache-2.0 MediaPipe SelfieMulticlass model supplies explicit masks for background, hair, body skin, face skin, clothes and `others/accessories`. Combined with the MediaPipe face/eye band, it detects both case07 glasses images and rejects four hard negatives (6/6 presence). This is a real semantic model, not an edge heuristic.

It is not yet ownership-qualified: `others/accessories` is broader than glasses and no independent per-pixel glasses masks were available. It is the selected commercially-clear parsing candidate, but case07 pixel validation remains NO.

## Memory

| Lifecycle | Model bytes | Measured peak RSS |
|---|---:|---:|
| Landmarker + L2-C geometry | 3,758,596 + 45,999 | 323,572 KiB |
| Landmarker + multiclass parser co-resident | +16,371,837 | 749,836 KiB |

Standalone geometry fits 512 MiB; the required parsing lifecycle does not. A 1 GiB isolated worker is feasible from measured RSS but lacks safe room for the warmed application and renderer. The provisional production recommendation remains 2 GiB with sequential worker lifetimes. This is not full-runtime memory qualification.

## Internal identity model feasibility

Before training, require an asset ledger granting commercial derivative-model rights. A credible minimum is 5k–10k licensed 3D identities plus synthetic augmentation to roughly 100k identity instances, 12–20 poses and 8–12 expressions each. Split by identity, with withheld real cross-view scans.

Proposed output: 128–256 intrinsic identity coefficients plus a compact 468×3 residual code, trained against neutral canonical geometry with explicit expression orthogonality, topology/orientation/ARAP and cross-view silhouette losses. A MobileNetV3-small or comparable encoder should remain around 10–30 MB weights and roughly 80–180 MiB inference RSS. Estimated first feasibility run: 2–4 modern GPUs for 3–7 days after licensed data preparation. These are planning estimates, not measured qualification.

Raw reproducible results are in `geometry/` and `parsing/`; asset hashes and licenses are in `tests/fixtures/v265_commercial_assets.json`.

## Commercial identity procurement (2026-09-09)

The decision-ready vendor qualification, exact vendor requests, offline export
contract and synthetic-first procurement route are recorded in
`vendor-identity-procurement.md`. No authorised MetaHumanSDK.io or Banuba identity
export was available, so no vendor was assigned invented quality scores. The new
independent glasses polygons confirm 6/6 presence classification but only 0.0212
mean pixel IoU: MediaPipe `others/accessories` is not ownership-qualified.
