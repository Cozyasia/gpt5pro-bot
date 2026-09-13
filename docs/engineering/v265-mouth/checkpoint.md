# First-principles mouth: neutral clearance passes, complete jaw admission blocked

PR120 only. Frozen negatives remain byte-for-byte in v265-anatomy/articulation:
legacy431 neutral intersection pairs, partial220, triangles7919/8103/8111/8115,
identity417 opening0.43710, A7117/B9903 reference-normal violations. No legacy
skinning tuning, no V4 training, no real photos, no merge/deploy.

## New construction

Original analytic mouth component, independent of broken V4 mouth coordinates:
seven64-vertex annular sections from outer integration rim through vermilion,
inner lips and cavity wall/back cap;12 separate closed dental primitives.
545 vertices,976 triangles,13 connected components (one oral surface+12 teeth),
one intentional64-edge outer boundary, zero non-manifold/winding/degenerate/
duplicate-face defects. Upper/lower cavity share continuous angular ownership;
upper teeth anchored, lower teeth rigidly hinge-owned. No lip/teeth shared vertices.
Local x/y/z axes represent horizontal/inferior/posterior. Neutral slit has0.4mm
positive clearance at its centre, not penetrative closure. It is an engineering
closed-mouth approximation, not calibrated human anatomy.

10 deterministic identity settings: mean, narrow/wide, thin/thick lips,
short/long philtrum transition, narrow/wide jaw transition, asymmetry.
This is component validation, not the512-identity training corpus.

## Measured improvement

All10 neutral settings: zero detected proper self-intersections, lip/lip,
lip/teeth and cavity/teeth penetrations; zero unresolved coplanar candidates.
Neutral signed corresponding lip depth separation3mm; minimum tooth/oral
triangle-surface distance4.152mm. Upper/lower dental minimum6mm.
Checks combine topology incidence and segment/triangle contact search with
point/triangle and edge/edge distance. Coplanar candidates fail closed.
Shared-vertex contacts/tangencies are not a certified exhaustive collision proof;
no continuous-time or arbitrary-parameter clearance certification is claimed.

All110 jaw states (10 identities x0,.1,...,1) retain contact/topology clearance.
Minimum tooth/oral distance2.0395mm; minimum upper/lower dental distance6mm.
Minimum signed lip depth projection0.9085mm; minimum corresponding-point distance
3.1100mm, minimum distance ratio0.98348. Correspondence distance is NOT globally
minimum wall thickness. Rigid dental distances and source immutability tested.

## Complete jaw gate REJECTED

Reference area ratios0.93785–10.59988, edge ratios0.68590–15.69956.
Worst: narrow identity, opening1.0, edge[192,193], inner-lip commissure.
The short neutral slit edge has insufficient material length for opening under
this operator. This is high strain, NOT a detected intersection or proven foldover.
No independent benign strain envelope exists; no automatic threshold relaxation.
The next prerequisite is a material-consistent commissure surface/articulation,
not coordinate nudges or mask/skinning tuning on the previous broken assembly.

Initial code c031052 incorrectly used contact PASS as jaw PASS. A partial expression
run began under that incomplete gate. It was stopped after the strain audit;
its partial counts are preserved as diagnostic only, never expression admission.
Code6b14f773e61f775f30d161006e271572cca56c64 explicitly separates jaw_contact_pass
from jaw_pass and tests that expressions reject contact-only admission.
The initial CI revision may execute those diagnostics; the corrected workflow
runs the contact/strain evidence and verifies the rejection instead. No trainer
is invoked by either revision. This sequencing correction is not hidden.

## Remaining stages

Expressions/full-anatomy sweep NOT_ADMITTED. Component outer rim is not yet
stitched into retained V4 face; it must not overlap the old mouth at runtime.
Retained eye/nostril/accessory contacts are NOT newly qualified. No StageA/B/C,
case06/08 model acceptance or V0. No large render corpus or paid compute.
External incoming-mail query once on2026-09-13 found no replies; no sends.

## Reproduce

From repo root WITHOUT root in startup PYTHONPATH:

```sh
OPENBLAS_NUM_THREADS=1 python -m experiments.v265_mouth.run /tmp/mouth
python -m unittest experiments.v265_mouth.test_component -v
# Expected controlled rejection: jaw contact PASS is insufficient.
python -m experiments.v265_mouth.expressions /tmp/mouth
```

results.json contains every jaw scalar and worst edge. No culling or geometry repair
is performed at inference. Geometry-distributions.json records additional paired
thickness measurements; raw component equations, identities and parameters are
versioned in experiments/v265_mouth/component.py. All primitives are original code,
no external face assets. Engineering-only; no real-human/commercial model claim.
