# V265 commissure mechanics — experimental checkpoint

Owner: PR #120 (`v265-self-hosted-l2`), parent research PR #119. Production main remains frozen at `c4bda09a98557e1bdea46338bccf66d8b6e6ed61`. No V4 training, real images, merge or deployment in this experiment.

## Frozen references

The 545-vertex / 976-triangle neutral assembly is unchanged. Ten original identities are checked against `experiments/v265_commissure/neutral-fixture.json`; exact vertex and topology hashes match. It has one 64-edge external attachment boundary, one continuous oral surface and 12 separate closed dental components. The old 431 / 220 intersections and A/B negative fixtures remain in their original directories.

The narrow identity edge [192,193] is the right inner-lip commissure, adjacent samples of ring 3. Its neutral length is 0.0841742 mm. Angular jaw weights jumped from 0.5 to 0.54900857 across this exceptionally short material edge. At opening .05 its stretch is already 1.341x, at .10 1.955x, at .15 2.659x, and at .20 3.397x. There is no late sharp onset: concentration starts at the first sampled nonzero opening. Exact neighbors, trajectories and angle sweep are in `local-map.json` and `d2/fixture.json`.

## Controlled candidates

C is a local barycentric fan control. It preserves the neutral surface but also preserves the original displacement gradient, so maximum stretch remains 15.699559x. Subdivision alone does not solve the mechanics; no claim of an optimized geodesic C is made.

D defines the corner as a half-weight kinematic anchor and distributes weights by cumulative neutral inner-lip material arc length. Edge weights become 0.5 and 0.50247504. The jaw angle remains 22 degrees at opening 1. Dental transforms are unchanged. The first D version reduced strain but reduced cavity/dental clearance to 0.00625 mm and was rejected; its source and results are preserved in `d1-negative/`.

D2 smoothly retains the original deep-cavity ownership while applying the material-arc anchor to lip surfaces. This is a depth-dependent kinematic transition, not a change to neutral anatomy or opening amplitude.

## Standalone jaw qualification

The primary 10 identities x 21 openings all pass contact checks. Maximum edge ratio is 1.466956814; minimum is 0.739128346. Area ratios range 0.820305151–1.780586632. Right one-ring strain concentration max/median is 1.363979620; the separate left-side diagnostic is 1.304208543. Reference-normal reversals are zero in these 210 states; this diagnostic is distinct from true self-intersection or camera-projected orientation.

Minimum surface distances over the explicitly defined disjoint outer-vermilion and inner-wall bands are: upper 2.890897 mm, lower 2.834889 mm, left commissure 2.184784 mm, right 2.196588 mm. The global band-pair minimum is 2.184784 mm. These are triangle-to-triangle distances, not predefined corresponding-point distances, but are not a certified minimum over an arbitrary anatomical lip volume. Primary-set minimum tooth-to-oral clearance is 2.039532 mm.

Calibration used 24 additional identities x 21 states. A frozen 20% engineering margin was then applied before testing a separate seed with 12 identities x 11 states. All 132 independent states passed. Their minimum global band separation is 2.181056 mm. This is a procedural engineering envelope, not a validated human-tissue strain range. See `d2/envelope.json`, `qualification.json` and `sealed-results.json`. The phase-local `d2/summary.json` deliberately retains its pre-qualification hold; the later qualification file records standalone admission.

Contact validation checks proper nonadjacent triangle intersections, rejects unresolved coplanar candidates, checks topology/winding/areas, dental clearance and signed inner/outer separation. Shared-vertex pairs are excluded; finite sweeps do not prove continuous collision freedom. Standalone admission is not face attachment or full anatomy admission.

## Soft-expression negative and correction

The original expression composition applies compression to coordinates already containing jaw opening. At mean identity, jaw opening 1, compression .75, it produced 16 lip intersections despite acceptable strain and dental clearance. The first detected crossing was bracketed at .5895414426922798–.5895414501428604, with triangle pairs [319,449] and [446,449]. Coarse .01 sweep first finds contact at .59. This is a CONTACT failure, not a strain threshold failure. Preserved source and results: `expression-negative/`.

The corrected operator computes soft displacement in the neutral mouth-local frame and transports it through the same weighted jaw frames. It does not scale the opening displacement. Teeth receive no soft displacement. The regression test retains the old collision and checks that maximum compression no longer reproduces it. The expression grid still gates attachment.

## Reproduction

Use Python with NumPy and no startup PYTHONPATH pointing at the repository (legacy root sitecustomize is not part of this experiment):

```sh
OPENBLAS_NUM_THREADS=1 python -m unittest experiments.v265_commissure.test_candidates -v
OPENBLAS_NUM_THREADS=1 python -m experiments.v265_commissure.pipeline /tmp/commissure
```

A scientific rejection is recorded in JSON and stops the pipeline; a successful CI execution is not a quality PASS. Expression tests are blocked unless independent jaw qualification passes. Attachment is blocked unless expressions pass. Full-anatomy training remains blocked until retained-face/seam articulation and contact are qualified.

## External status

One incoming-mail search on 2026-09-13 found no new matching MetaHumanSDK / FaceVerse / Synthesis AI / 3D-Ace messages since 2026-09-12. No new outgoing message or financial commitment. Last known statuses: MetaHuman access pending, FaceVerse rights pending, Synthesis and 3D-Ace RFQs sent. A search result is not proof of delivery or a comprehensive mail audit.

## Final measured endpoint

The corotated expression operator passes 320 states: 10 identities, jaw 0/1, four individual soft modes, coefficients .25/.5/.75/1. This covers each requested mode alone and with maximum jaw opening, not every simultaneous multi-mode or intermediate-jaw combination. It is a finite engineering grid.

Attachment was then attempted and rejected. The combined neutral prototype has 803 proper intersection pairs: 782 within retained face anatomy, 14 seam/seam and 7 seam/face. None involves the new mouth triangles. It has 6 non-manifold edges and 7 inconsistent-winding edges. The retained contacts are predominantly eyeball/eyelid and also nostril surfaces. Exact pairs, seam IDs and semantic counts are in `expression-corrected/attachment*.json`.

Consequently: standalone jaw and tested expression grid pass; mouth-to-face attachment and full anatomy fail. No Stage A/B/C, real frozen matrix, V0 or human sheet. The next measured blocker is retained eye/nose contact plus the local attachment seam, not commissure strain. The attachment prototype has not qualified propagation of jaw motion through the retained face.

Code: `56144ad316a923238738ebc13383930887ac9686` (D2 qualification), `56181482672bf47969eed905107ce91ce5e9b8f9` (corotated soft expression). The latter has all three successful workflows, including commissure run 34751563424.

CI-only commit `fa78742155d9234ccf4c2c922571d10c8b9e2ee1` stops automatic RELIEF-V3 training on PR updates while retaining generator contract tests. The previous PR-wide path filter had automatically re-executed the frozen historical benchmark; those results are not used as new quality evidence. Manual reproduction remains available without modifying frozen artifacts. On this CI-only commit the quality contract workflow succeeded; the selfhost job hit a Docker Hub connection reset before build and received one failed-job retry.
