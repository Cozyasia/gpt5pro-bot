# G2 pair proof execution plan — 2026-09-27

The user's accepted specification is the 14-point proof-oriented cycle: unchanged G2,
89 unresolved neighboring material cells, no epsilon exclusion, no downstream stages.
Execute inline on the existing isolated experimental branch v265-self-hosted-l2.

## Proof design

For a shared edge a,b and third vertices c,d, glue the two reference prisms:
K = {(u,y,w): u>=0, u+|y|<=1, 0<=w<=1}. This is convex.
For y>=0 use A's barycentrics (1-u-y,u,y); for y<=0 use B's
(1-u+y,u,-y). The maps agree exactly at y=0. Frozen binary64 outer
and inner vertex coordinates are treated as exact rationals; no coordinate is moved.

A fixed nonsingular spatial preconditioner C and positive diagonal S are proposals
only, selected numerically. Certify the symmetric part of S*C*J*S^-1 positive
definite throughout both cells using exact rational interval bounds and adaptive
subdivision. Then the continuous piecewise differentiable map is strictly monotone
in the scaled reference coordinates: integrate its derivative along the straight
segment in convex K. This proves injectivity of the glued pair, including each
cell separately. Cross-cell equality is therefore confined to y=0 with identical
u,w. This is an analytic reduction of the six-parameter equality problem, not
a sampled or enclosure-only collision test.

First retain spatial-coordinate interval overlap diagnostics for the two complete
material maps. Subdivide potentially conflicting proof domains to certify the
derivative inequality. Strict positive interval pivots are required. No epsilon
changes proof outcomes. A resource limit returns UNRESOLVED_NUMERICAL.
This sufficient proof need not work for every injective map; rejection is not collision.

The infimum of interior-interior physical separation for adjacent cells is zero.
Report zero, not a fabricated positive minimum; record a positive monotonicity
coefficient separately, and lower spatial separation bounds on excluded boxes.

## Tasks

1. Add failing tests: exact interval inclusion, separated prisms, common interface,
   real overlap, arbitrarily small positive separation, budget fail-closed, replay.
2. Implement rational intervals, exact material parameterization, proposal and
   adaptive positive-definiteness certificates. Preserve full leaf proof data.
3. Resolve representative 7676/7747 first, then all 89 with identical code. Record
   hashes, exact counts, coordinate/parameter boxes, depth and residual widths.
4. Independently review theorem and implementation; replay certificates, run frozen
   tests, publish code on PR120, inspect CI code SHA, publish evidence separately.

## Admission scope

Resolving these 89 proves those pairs only. Re-audit the preexisting numerical
449 separators, remaining enclosure exclusions, boundary/globe exclusion, and
single-cell coverage before any full GLOBAL INJECTIVITY or neutral PASS claim.
Never change the existing fail-closed admission flag merely because this subset passes.

## Review focus

- Shared-interface identity and convexity of the glued reference domain.
- Exact rounded-coordinate semantics vs original field arithmetic.
- Fixed preconditioner across all leaves (local certificates alone are insufficient).
- Coverage of clipped triangular parameter domains and exact zero boundaries.
- Resource exhaustion, malformed/degenerate cells, true collisions must not PASS.
