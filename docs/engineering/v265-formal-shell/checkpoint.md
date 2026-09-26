# Formal local shell feasibility — G2 neutral candidate

Production frozen. PR120 only. Frozen mouth D2/corotated expression, nose V2, retained exterior and old uniform/E/F/G negative files unchanged. No blink/seam/training/real matrix/merge/deploy. This is nominal neutral geometry evidence, not dynamic or identity-diverse admission.

## A. Formal cone map

For all 284 material vertices, solve max rho subject to N*d >= rho and each d coordinate in [-1,1], using every incident oriented facet. Directions are normalized only after solving; every normalized direction is checked against every facet. FEASIBLE_CONE 284; DEGENERATE_CONE 0; EMPTY_CONE 0. Minimum normalized facet dot 0.18398318597507618. The old 19 averaged-normal failures do not imply empty cones.

Classification is numerical LP with tolerance 1e-9, not exact rational arithmetic. An EMPTY nonzero cone would mean the closed homogeneous cone contains only zero. Six signed cube-face feasibility problems and positive-dependence certificates are implemented for this case; no such witnesses occur in this dataset. All incident IDs/normals/directions/ownership are in cones.json. Globe/nonincident obstacles are handled separately, not conflated with the homogeneous local cone.

## B. Continuous field and limits

A single C0 piecewise-linear field interpolates the max-margin directions. No smoothing/offset/parameter sweep. Material map per exterior triangle is F(u,v,s)=sum b_i*p_i+s*sum b_i*d_i, s in [0,0.08178562867 mm]. Its determinant is affine in barycentric u,v and quadratic in s. Checking the three triangle corners and each quadratic's interval endpoints/stationary point covers the entire cell, not just samples. Minimum determinant 1.8709729701347102e-7 m², positive in all 426 cells. Maximum neighboring unit-direction difference 1.580335; C0 continuity is established, not low curvature.

The prospective outer/inner/rim boundary has zero detected proper intersections/coplanar overlaps/topology defects at the one frozen depth. 2,982 thickness-segment samples are clear; vertex obstacle rays are clear. These facts alone do NOT certify a globally injective volumetric map.

Global convex-enclosure test: 426 cells, 2,528 broadphase pairs, 538 overlapping enclosures, all sharing an exterior edge. These are not actual shell collisions. An analytic common ruled-interface separator resolves 449. Remaining 89 fail this sufficient separator, not necessarily the geometry. Exact cubic inversion at each of the 89 enclosure witness points finds zero double interior preimages. This is negative evidence of collision at those points, not an injectivity theorem. Full global injectivity remains UNQUALIFIED.

## C. Decision

G2 selected as the one neutral probe after strict local cones, positive local material Jacobians and clear prospective discrete boundary. H NOT_RUN. G family is NOT structurally rejected: no empty-cone or genuine material-overlap witness has been established.

Important scope: the user's complete collision-free-field eligibility requirement is not yet certified. G2 is an unadmitted feasibility probe, not a completed G2 qualification. Do not interpret the selection as formal global feasibility PASS. No G3/H2 and no exterior relaxation.

## D. Frozen contracts

Remote commit 4c886a6a00a89cea513702d14fd053101ee699b8 freezes the contract before final G2 material admission. Original local pre-evaluation commit 8e271fe; tree published through GitHub API. Contract SHA256 0a49cc6d770f46aa22ea9c9feb5b602a73d9cb265dedec4bc6038942f8065dc3.

Inherited and unchanged: exterior deviation zero; inner/globe floor 0.164523871 mm; material wall floor 0.040892814 mm; construction depth 0.081785629 mm; zero proper/coplanar crossings. Added: positive material-map Jacobian everywhere, no material segment crossing, finite canthus neighborhood, and global injectivity certification. Missing certification cannot be replaced by more samples.

Material thickness is min norm(sum b_i*T_i), the distance from the origin to the displacement-vector convex triangle. It is not nearest outer/inner surface distance. The measurement handles rank-zero/one displacement triangles without NaN. A constant direction is a valid material field, not a degenerate anatomical triangle. An initial use of the older nearest-triangle routine produced nonfinite measurement entries; fixing this measurement did not change candidate coordinates or thresholds.

## E. One neutral candidate result

| Check | Result |
|---|---:|
| Vertex / triangle count | 5,528 / 10,664 |
| Exterior coordinates/triangles bit-exact | YES |
| Detected proper / positive-area coplanar intersections | 0 / 0 |
| Nonmanifold / winding / degenerate / duplicate faces | 0 / 0 / 0 / 0 |
| Minimum material thickness | 0.050125663 mm |
| Thickness floor | 0.040892814 mm |
| Minimum canthus material wall | 0.081785629 mm |
| Minimum inner canthus neighboring edge | 1.203519728 mm |
| Thickness-segment samples / hits | 2,982 / 0 |
| Local material Jacobian | positive, full interval |
| Global injectivity | UNQUALIFIED |
| Neutral admission | NOT ADMITTED |

| Clearance, mm | Right | Left |
|---|---:|---:|
| Exterior -> globe, unchanged | 0.527095036 | 0.588008914 |
| Inner -> globe | 0.454467142 | 0.524194084 |
| Nearest outer/inner diagnostic only | 0.015459294 | 0.021277183 |

Nearest outer/inner distance is smaller than material thickness and is not substituted into its contract. Both separate globe clearance contracts pass. No real-human or dynamic claim.

## F. Exact unresolved witness

Material pair 7676 / 7747, common edge 4041–4042, third vertices 1398 / 4077. The implicit ruled-interface Q/v ranges are [-9542.810190,-1318.413447] and [-736.890483,738.938863]; the second range changes sign, so that sufficient separator fails. Basis condition number 945.556221. This does NOT prove physical overlap; enclosure witness inversion found no double interior preimage. All 89 unresolved pairs and 538 enclosure witnesses are retained. Minimum thickness witness: left triangle 9026.

The remaining task is certification of these neighboring material prisms (or a genuine crossing witness), not coefficient tuning. Stopping on this admission blocker preserves the one-candidate rule. Blink remains NOT_RUN.

## Verification / provenance

Tested code ecd38ce01a50092bac9aff439ac50eba9afb5fbb. Eight local tests pass (cone classification, material minimum including constant field, positive/inverted prism, ruled separator, inverse mapping, inherited floors, fail-closed admission, retained fixtures). No production files changed. Parent prior HEAD 6bdab9fa78f0a50304531c85a4356a8a2141f375. Author self-review only; no independent reviewer was used.

Reproduce with OPENBLAS_NUM_THREADS=1 and modules experiments.v265_formal_shell.{cones,field,preflight,global_field,witness,admission}, in that order, all using the same output directory. Python 3.11, numpy 2.3.5, scipy 1.17.0. No training commands.

One incoming mail search after 2026-09-14 found no MetaHuman/FaceVerse/Synthesis/3D-Ace replies. No outgoing mail or financial action.

CI for tested code: formal neutral shell 36278162833 SUCCESS; quality contracts 36278165088 SUCCESS; self-hosted engineering 36278165087 SUCCESS (both isolated mock jobs). Those existing mock CI jobs are regression checks, not V4 training. Evidence-only publication uses [skip ci].
