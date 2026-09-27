# Retained eye/nose repair — failed full-blink admission

Production frozen; PR #120 only. No V4 training, real images, merge or deploy. Mouth D2 and corotated expression code are unchanged. `mouth-positive.json` pins operator/source/envelope hashes and per-identity D2 weights, in addition to existing neutral geometry hashes. Nine local contract/regression tests pass.

## Old contacts, separate from seam

The original 782 retained contact pairs came from the mean attachment prototype only. No identity-diverse old attachment evidence exists. Exact original triangle IDs and semantics are in `old-root-map.json`:

| Contact group | Pairs |
|---|---:|
| Eyeball / upper lid or orbital transition | 317 |
| Eyeball / lower lid or orbital transition | 412 |
| Eyelid / eyelid or transition | 12 |
| Nasal cavity or transition | 21 |
| Nostril/ala or transition | 20 |

Upper/lower grouping uses the lid/transition triangle centroid relative to the eye centre. Original skin-labelled transition triangles are not falsely relabelled as pure eyelid. Proper intersections have zero unsigned surface distance; that is not a penetration-depth measurement. None is waived as intentional adjacency. Old 14 seam/seam and 7 seam/face contacts remain frozen separately.

## Local replacement

Only old eye/nose insertions are replaced; base skin is retained. Frozen mouth is absent from this retained gate. Prototype has 5,244 vertices / 10,096 triangles. Eyes use a separate closed rigid ellipsoid behind a continuous three-band lid and aperture. Nominal globe radii are 12/7/7 mm; this is an original procedural prototype, not established identity diversity. Lids follow the front ellipsoid offset, with upper/lower opening controlled independently of globe motion. A 0.1 mm minimum triangle-surface clearance policy is enforced; no proper crossings permitted.

Nose V1 still had eight crossings because radial contraction of a concave grid aperture is not injective. V1 source/results are preserved. V2 extrudes the actual ordered concave boundary posteriorly and ear-clips its planar back closure; no centroid fan crossing or duplicate sheets. This removes detected nose contacts without adding resolution.

The old contact routine marks any coplanar AABB candidate unresolved. Twenty such candidates at the planar closure are resolved by a 2-D separating-axis triangle overlap test. All have zero positive-area overlap. The overlap test rejects a deliberately overlapping coplanar fixture and accepts a separated fixture. This is narrow-phase geometry resolution, not a relaxed penetration threshold. Shared-edge/point adjacency has zero overlap area.

## Measured outcome

Neutral: zero proper intersections, zero positive-area coplanar overlap, zero non-manifold edges, zero inconsistent winding, zero degenerate or duplicate triangles. Eye surface clearance: left 0.588009 mm, right 0.527095 mm.

Blink 0/.25/.5/.75 passes structural checks. At blink 1 there are six lid/lid proper crossings, but no eyeball or nose contacts. The first lid-subset crossing is bracketed between 0.9317340850830078 and 0.9317343235015869, triangle pair [9030,9033]. Exact coordinates are saved in `blink-onset.json`. Clearance to the globe remains at least 0.492835 mm at blink 1. This is SELF_INTERSECTION of the eyelid interpolation near closure, not eyeball penetration, not projected backface change. The coefficient is not reduced to hide the failure.

Only the nominal prototype was tested. Squint and pose combinations stop after the first failed blink. No assertion of full retained identity/expression qualification is made. Neutral structural admission passes locally; full retained admission fails.

A boundary-traversal / arc-length seam implementation is prepared but has NOT RUN because retained dynamic/contact admission failed. It does not sort boundary vertices by angle and never modifies frozen mouth. Neutral attachment, attached jaw, full-face factorial, full anatomy and Stage A/B/C remain blocked.

## Reproduction and provenance

```sh
OPENBLAS_NUM_THREADS=1 python -m unittest experiments.v265_retained.test_contract experiments.v265_commissure.test_candidates
OPENBLAS_NUM_THREADS=1 python -m experiments.v265_retained.admission /tmp/retained
OPENBLAS_NUM_THREADS=1 python -m experiments.v265_retained.onset /tmp/retained/onset.json
```

Code SHA: `1995aacd51b9f359cc8d1502daefc647d5ddca79`. Source algorithms are original procedural code; no new external model/assets. Source/weights/envelope hashes guard the frozen mouth. Full anatomy admission is fail-closed; successful CI means reproducible engineering, not anatomical PASS.

One incoming-mail search on 2026-09-13 found no matching new vendor responses since 2026-09-12. MetaHuman and FaceVerse pending; Synthesis and 3D-Ace RFQs sent. No outgoing follow-up or financial commitment.

CI on tested code SHA 1995aacd51b9f359cc8d1502daefc647d5ddca79: retained admission 34765561228 SUCCESS; quality contracts 34765563577 SUCCESS; selfhost 34765563576 SUCCESS (both isolated jobs). Evidence commit is documentation-only and skips CI.

The onset pair lies on the lower portion of the left lid (x negative, y greater than -26 mm). Neutral boundary cycles have 256 / 61 / 36 / 35 edges: outer face, reserved mouth, and two eye apertures. These are intentional boundaries at this standalone stage, not qualified attachment cracks.
