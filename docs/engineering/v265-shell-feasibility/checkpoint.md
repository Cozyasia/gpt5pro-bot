# Eyelid neutral shell feasibility

Experimental PR #120; production frozen. Mouth D2/corotated expressions, nose V2, frozen exterior and old/E/F/uniform extrusion fixtures are unchanged. No blink, seam, training, real matrix, merge/deploy.

## A. Root cause of 40 uniform-offset crossings

Exact pair IDs and ownership: `root-map.json`. Right 20 / left 20; all 40 lower lid; orbital band 8 / middle 16 / margin 16; all central under the declared 8 mm canthus-zone cutoff. The cutoff is a reporting partition, not a safety threshold. Same topology ordering as the exterior is retained. A global posterior translation moves the duplicated sheet through nearby portions of the curved exterior. No new non-manifold defect is needed to create these crossings.

`fields.json` records each of 284 material vertex samples: coordinates, normal/posterior ray's nearest nonincident exterior triangle, separate globe ray and point-to-globe distance, local normal-change length. Null ray hit means no sampled ray intersection, not infinite free space. Adjacent incident triangles are excluded from ray testing and checked separately by the final normal-cone guard. This remains vertex sampling, not continuous surface certification.

## B. Available envelope and corrected feasibility interpretation

Initial heuristic depth budgets (minimum / 5th percentile / median / maximum) were 0.163571 / 0.301338 / 0.752775 / 2.648002 mm. These came from fractions of normal-change length, exterior ray obstruction, and globe distance. They are NOT certified maximum collision-free thicknesses. Minimum initial sample: vertex 4687 at [-32.107601,-21.563636,-4.890216] mm; normal ray encounters exterior triangle 9030 at 1.357251 mm, but local normal-change length limits the heuristic budget first.

The first G probe exposed a missing preliminary check: averaged normals can point outward relative to some incident facets, even when nonincident rays are clear. There are 19 such directions. Witness: vertex 1720 at [36.003121,-15,-6.903880] mm, incident triangle 7707, direction [0.0137221,0.2571737,0.9662678], incident-normal dot -0.3006961. `normal-cone-witnesses.json` records all witnesses. This chosen direction has no positive interval satisfying every incident oriented tangent half-space. It does NOT prove the whole frozen exterior admits no alternative shell direction or topology.

The initial ray-only feasibility precheck was insufficient and should not be treated as permission for a certified shell. Final code now blocks construction on any such direction, before generating inner geometry. Regression tests require the 19 witnesses to be detected. Minimum necessary exterior relaxation is NOT ESTABLISHED; no exterior changes are justified or performed.

## C. G vs H design

| | G, selected probe | H, design only |
|---|---|---|
| Inner geometry | Existing material sleeve, local exterior-normal directions | Separate globe-conformal palpebral strip from margin to orbital attachment |
| Correspondence | Frozen outer-to-inner IDs | New inner material chart tied to preserved outer rim |
| Main risk | Incompatible incident normals / offset self-contact | Outer/inner separation and canthus continuity not implied by globe conformity |
| Execution | One probe rejected; corrected precheck blocks repeat | NOT_BUILT after neutral FAIL |

G was selected as the smaller construction change, with no outer-coordinate movement. H is not an evaluated candidate and has no quality claim. No offset sweep or third family.

## D. Contracts frozen before candidate evaluation

Commit `0c7cfcae5593a952e0aeaa97ded691c9a8910ad7` froze the contract before G construction. Its fields SHA matches the preserved original feasibility fields. Four separate metrics:

1. Exterior-to-globe: frozen regression, exterior/globe geometry unchanged.
2. Inner-to-globe: engineering floor 0.164524 mm, one quarter of minimum sampled exterior-point/globe distance.
3. Wall thickness: engineering floor 0.040893 mm, one quarter of minimum initial depth budget. Construction depth 0.081786 mm, one half of that budget.
4. Outer/inner crossing: zero proper crossings and positive-area coplanar overlaps, independent of unsigned distances.

These fractions are prospective conservative engineering choices, not physiological norms or independently validated anatomical limits. They were not calibrated on G failures and have NOT been changed after rejection. A positive distance is never accepted as wall thickness when proper crossings exist.

## E. G neutral result and stop

The probe at code `5ac39184cf4fb32e5f66365d5c9b1319518f5142` produced 90 proper intersections; non-manifold/winding/degenerate defects are zero. Wall-thickness gate fails. Frozen exterior deviation is zero.

| Metric | Right | Left |
|---|---:|---:|
| Frozen exterior -> globe, mm | 0.527095 | 0.588009 |
| G exterior -> globe, mm | 0.527095 | 0.588009 |
| G inner -> globe, mm | 0.477662 | 0.529405 |
| Inner clearance floor passed | YES | YES |

Thus decreased INNER clearance is correctly not called exterior regression. Both clearance contracts pass; self-contact and thickness do not. Detailed failed probe including exact pairs: `g-probe.json`; its source is frozen in `g-probe-source.txt`.

Final preconstruction code `26272d07564fe02e9bc561ed3dd76eeafe4d67f4` rejects all 19 incompatible directions and returns NOT_RUN for construction. This is an earlier failure gate, not a successful new shell. Neutral shell FAIL; blink/retained dynamic/seam/full anatomy/training remain blocked.

## Reproduction

```sh
OPENBLAS_NUM_THREADS=1 python -m unittest experiments.v265_shell_feasibility.test_contract experiments.v265_retained.test_contract
OPENBLAS_NUM_THREADS=1 python -m experiments.v265_shell_feasibility.analyze /tmp/shell
OPENBLAS_NUM_THREADS=1 python -m experiments.v265_shell_feasibility.candidate /tmp/shell
```

No vendor reply found in one incoming search since 2026-09-12. No outgoing mail or paid action. MetaHuman/FaceVerse pending; Synthesis/3D-Ace sent.

Final tested-code CI: shell feasibility 34783198918 SUCCESS; selfhost 34783202190 SUCCESS; quality contracts 34783201846 SUCCESS. Evidence-only commit skips CI.
