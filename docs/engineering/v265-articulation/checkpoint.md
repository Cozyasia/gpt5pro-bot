# Mouth mechanics: admission remains rejected

Parent: da73ae53f3eb81603b75d190a6086081aff3a662, PR120 only.
No V4 training, RELIEF-V3 tuning, real photos, production mutations, merge/deploy.

## Root cause

The 25 legacy normal failures involve triangle IDs7919,8103,8111,8115.
The 7mm opening addend is applied only to semantic lip vertices, stopping at the
cavity wall; the sign split also creates a discontinuity across commissures.
Triangle8111 joins two inner-lower-lip vertices to one lower-cavity vertex.
The report includes all vertices, one-ring neighbors, XYZ/UV, coefficients,
first crossing along each expression ray, projected signed double area, actual
unsigned area and single-mode ablations. Identity417 fails with opening alone.

IMPORTANT: a negative dot against the neutral normal is not automatically a
zero-area collapse or a complete proof of local3D foldover. Separate non-adjacent
segment/triangle contact witnesses are logged. The legacy neutral identity417
already has431 proper triangle intersection pairs in the mouth/teeth subsystem.
Thus its previously green edge-incidence/winding test was insufficient for contact
validity. Coplanar candidates remain unresolved and reject; absence of a witness
is not complete clearance, especially tangencies and shared-vertex collisions.

## Two mechanical candidates, same assembly

Both add a separate lower dental row:5916 vertices/11502 triangles. Upper dental
vertices stay anchored; lower dental vertices follow rigid22-degree maximum jaw
rotation around approximate hinge(0,-.015,.035)m. This is an engineering hinge,
not subject-calibrated anatomy. Chin/skin use bounded weights. Teeth do not receive
soft lip displacement. Stored neutral geometry is immutable and neutral expression
returns a bit-exact copy. Dental rigid-distance tests pass.

A uses upper/lower material ownership weights propagated consistently through depth
rings. B uses smooth local cage weights. B is a **diagnostic cage deformation**, not
an implemented constrained optimizer. Neither candidate is admitted. Pre-raster
admission rejects neutral/posed intersections, normal reversals, area degeneration,
and missing independently calibrated edge/area bounds. Full contact/visibility
clearance is explicitly missing; the gate cannot silently PASS.

On four withheld identities416,417,428,443, both candidates use35 combinations:
opening0,.25,.5,.75,1 times neutral/smile/compression/protrusion/asymmetry/blink/squint.
Total280 cases. A:7117 reference-normal violations; max1099 contact pairs.
B:9903 violations; max1054 contact pairs. These totals are over all cases, not unique
triangles. No candidate selected. No culling, fallback, coefficient sweep or training.

A separate loop-coordinate reconstruction (NOT a third articulation candidate)
uses regular angular sampling, separated depth layers and enlarged cavity. It
still has220 proper neutral contact pairs on identity417. This rejected attempt
is retained. It is not a valid closed-mouth topology repair.

## Explicit incomplete requirements

No complete lip/cavity/tooth contact clearance; no validated commissure joining;
no calibrated benign area/stretch envelope; no reliable teeth exposure or cavity
coverage; no independent full anatomy yaw/pitch/nostril sweep. Consequently no
mouth metric completeness claim, no V4 rendered corpus, StageA/B/C, pose-invariance
A/B, ONNX or V0. These are unrun, not negative trained metrics.
The concrete next prerequisite is reconstruction of a nonintersecting joined
lip/cavity surface, including neutral closure and dental enclosure. Jaw skinning
on this invalid assembly cannot establish admission.

Neutral identity controls/rank unchanged:80 factors; numerical rank319 at1e-5,
99% energy23,99.9%52. No new rank/quality claim.512 neutral geometries remain;
zero training renders. Mechanical benchmark local peak RSS40876KiB,149.30s.
This is NOT an isolated2GiB training qualification.

## Reproduce

From repo root, no startup PYTHONPATH pointing to root (legacy sitecustomize):

```sh
python -m experiments.v265_articulation.root_cause > /tmp/root.json
python -m experiments.v265_articulation.rebuild_diagnostic > /tmp/rebuild.json
OPENBLAS_NUM_THREADS=1 python -m experiments.v265_articulation.benchmark /tmp/mechanics
python -m unittest experiments.v265_anatomy.test_generator experiments.v265_articulation.test_mechanics -v
```

Six mechanics regression tests plus six prior anatomy tests. They establish limited
mechanical contracts and preserved rejection, not anatomy quality. All added
geometry/code is original analytic engineering work with no external face assets.
External incoming-mail search performed once; no matching replies, no sends.
MetaHuman/FaceVerse pending; Synthesis/3D-Ace RFQs remain sent, rights unconfirmed.
