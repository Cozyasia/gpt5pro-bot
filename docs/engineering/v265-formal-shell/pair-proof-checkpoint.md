# G2 exact neighboring-cell proof checkpoint — 2026-09-27

The former 89 unresolved pairs are now **89 ALLOWED_SHARED_INTERFACE**.
Zero forbidden intersections and zero unresolved cases in this input set.
G2 geometry, field, thickness, thresholds and retained exterior are unchanged.
No H/G3, blink, seam, training, paid operation, merge or deploy was performed.

## Exact result and its boundary

| Item | Result |
|---|---|
| Input pairs | 89 |
| CERTIFIED_SEPARATE | 0 |
| ALLOWED_SHARED_INTERFACE | 89 |
| CERTIFIED_FORBIDDEN_INTERSECTION | 0 |
| UNRESOLVED_NUMERICAL | 0 |
| Pair 7676 / 7747 | ALLOWED_SHARED_INTERFACE |
| Maximum subdivision depth | 1 |
| Numerical tolerance in acceptance | 0; exact rational inequalities |
| Interior-interior distance infimum | 0 m; not an attained forbidden equality |
| Complete-shell GLOBAL INJECTIVITY | UNQUALIFIED |
| New complete neutral admission | NOT_RUN; G2 remains NOT YET ADMITTED |
| Blink / seam / training | NOT_RUN / BLOCKED |
| Production | FROZEN |

These 89 pairs involve 157 distinct cells out of 426. Their successful proof is
not a certificate for every cell and every pair of the complete shell. The older
449 ruled separators and other convex-enclosure exclusions are still floating
numerical evidence. Complete volume-versus-unrelated-exterior/globe exclusion and
allowed boundary contact classification also need a globally assembled certificate.
This is the remaining proof obligation, not evidence against the geometry.
No geometry correction is justified by this cycle.

## Material maps and interface proof

For shared edge endpoints a,b and third vertices c,d, use the convex glued domain

`K = {u >= 0, u + |y| <= 1, 0 <= w <= 1}`.

On A (y>=0), barycentrics are `(1-u-y,u,y)`. On B (y<=0), they are
`(1-u+y,u,-y)`. Map each cell by the full bilinear-in-depth material formula.
Both maps agree exactly at y=0. Cells' local vertex order is explicitly reordered
to `[a,b,c]` and `[a,b,d]`; source triangle IDs/sets are checked.

Two representations are separately certified:

1. Exact rationals of the frozen rounded outer/inner endpoint coordinates,
   `F = sum b_i ((1-w) P_i + w Q_i)`.
2. Original continuous field formula, `F = sum b_i (P_i + w*h*d_i)`, with exact
   rational products of the frozen binary64 h, directions and positions.

The authoritative input positions come from the previous `cones.json`, not a fresh
trigonometric regeneration of the face. This matters: Python/runtime differences
in regenerated floating geometry produced different full-mesh hashes during audit.
The frozen source positions exactly matched the original local candidate's material
vertices and rounded inner coordinates. The final proof hashes these serialized
positions, their inner endpoints and integer topology. It does not claim identical
hashes for regenerated nonmaterial floating coordinates across environments.

A numerical optimizer proposes a fixed invertible spatial matrix C and positive
diagonal S. Optimization success alone grants nothing. For each cell, exact
rational intervals bound every entry of

`sym(S C J S^-1) - mu I`, with exact positive mu.

Each Jacobian entry is affine in the three material parameters. Extrema over a
clipped triangular box times a depth interval therefore occur at its vertices.
Exact interval Sylvester minors strictly above zero certify positive definiteness.
If an interval test is inconclusive, split parameter boxes adaptively; a depth or
node limit returns UNRESOLVED_NUMERICAL, never PASS or collision. No epsilon exists
in these decisions. Sampling and eigenvalues only propose a preconditioner.

For scaled reference coordinates z=Sx, the transformed map H(z)=S C F(S^-1 z)
satisfies `(H(z1)-H(z0)) dot (z1-z0) >= mu*||z1-z0||^2` by integration along the
straight segment in convex SK. The continuous glued map is piecewise differentiable;
the common interface has identical tangential derivatives. Thus equality of the
physical maps implies identical reference coordinates. Across the two cells this
can occur only at y=0, with equal u and w: the permitted shared material interface.

This is an analytic reduction of the requested six-parameter intersection problem.
It is stronger than rejecting finite sampled collision points. Spatial coordinate
intervals and first overlapping boxes are retained, but overlapping boxes are
resolved by the full-domain injectivity certificate rather than by infinite
subdivision around a permitted zero-distance interface.

## Representative pair 7676 / 7747

- Shared outer edge: 4041–4042; third vertices: 1398 / 4077.
- Both full root parameter boxes have overlapping spatial bounds; retained in
  `pair-7676-7747.json`, together with exact maps, inner IDs and source directions.
- Both mesh and formal-field certificates resolve at depth 0, two leaf domains
  per representation, with no excluded interface neighborhood.
- For the rounded-endpoint map, the certified scaled monotonicity coefficient is
  approximately 0.13360477571421162; the exact rational is in the certificate.
- A physical separation lower bound is supplied as a positive coefficient times
  scaled parameter separation. This is not a constant wall gap.
- Spatial root residual interval widths are approximately 4.452602, 4.546456 and
  3.322100 mm. Large root widths do not weaken the exact monotonicity proof.
- Infimum of unrestricted interior-interior separation is zero: distinct interior
  points can approach the common interface arbitrarily closely. There is no
  positive minimum to report, and no equality outside the interface.

Across both representations of all89: 368 proof nodes, 362 leaves and 6 splits.
Three pairs require depth 1: 8896/8965, 8960/8961, 8964/8965.

## Verification, review and reproduction

19 local tests pass; CI separately executes the proof and source-bound replay.
Replay reconstructs frozen input maps, checks source and per-file hashes, checks
exactly the original89 unique IDs, verifies complete subdivision coverage, and
recomputes every rational inequality without rerunning the optimizer.

Independent review found no flaw in the monotonicity proof or the initial89 mesh
certificates. It independently replayed all89, checked hashes and source coordinates.
Its two qualifications were addressed: dual map semantics and persistent source-bound
replay. A subsequent runtime reproducibility finding was fixed with a failing-then-
passing frozen-coordinate test. No full-project training suite was invoked.

The archived certificates are permanent Git evidence, independent of CI retention.
Extract `pair-proof-certificates.tar.xz` into an empty temporary directory, then run
`OPENBLAS_NUM_THREADS=1 python -m experiments.v265_formal_shell.prove_unresolved DIR --replay`.
Generate fresh certificates with the same module and directory argument without
`--replay`. `pair-proof-manifest.json` records TESTED CODE SHA and CI IDs separately
from the evidence-only PR HEAD. Old evidence is preserved as historical evidence.

PR CI was made contract-only for the self-host engineering workflow: mock training,
export and real-photo bootstrap are skipped on pull_request. No manual workflow
dispatch was issued. All frozen production and negative-fixture files are unchanged.

## Next proof step

Assemble a coverage-complete certificate over all426 cells: exact single-cell
injectivity, every remaining intercell exclusion/contact, and exclusion of unrelated
exterior/globe geometry. Reuse the unchanged G2 data and this verifier wherever its
preconditions hold; use certified spatial separation for other pair types. Only a
complete coverage manifest with zero unresolved obligations can replace the current
fail-closed GLOBAL INJECTIVITY flag and permit full neutral admission.
