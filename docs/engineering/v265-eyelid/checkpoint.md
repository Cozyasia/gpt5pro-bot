# Eyelid closure controls — rejected, baseline preserved

Owner PR #120. Mouth D2/corotated expression, nose V2 and retained neutral geometry remain unchanged. No training, real matrix, seam execution, merge, deployment or external face API use.

## Frozen neutral and old witness

`experiments/v265_eyelid/neutral-positive.json` pins retained neutral vertices, topology, eye insertion, globe, nose and mouth-positive manifest. `neutral-vertices.zlib.b64` stores the exact reference float64 bytes whose SHA is verified. E/F both reproduce generated neutral coordinates bit-exact in the same runtime; non-eyelid vertices and all triangles remain unchanged at every tested endpoint.

Raw recomputation SHA differed between local runtime and CI. Rather than replace the historical hash, the test verifies serialized reference bytes and bounds cross-runtime recomputation at 1e-15 metres, printing the measured difference. This is numerical reproducibility only; geometry/contact acceptance thresholds are unchanged. Initial failing CI is preserved as run 34768068433. Same-runtime bit-exact checks remain mandatory.

`old-blink-root.json` records vertices of triangles [9030,9033], their neighborhood, neutral positions, lower-left ownership, 0 plus .90:.005:1 trajectories, areas, local edge ratios and reference-normal dot products. Opposite-vertex signed triangle-plane distances are logged explicitly as plane distances, not certified penetration depth. Reference-normal reversal is not automatically a true foldover.

## Controlled candidates on unchanged topology

E defines an identity-dependent closure curve from upper/lower margin samples (65% lower / 35% upper blend), tapered to identity-owned canthi. Margin y moves monotonically toward that curve, with distributed band weights and a common globe-offset target depth. This is a controlled geometric prototype, not validated anatomy.

F uses the same closure targets while transporting each band vertex along its local globe-centred yz arc. It preserves each vertex's radial support distance instead of interpolating posterior depth. It is a local corotated control, not a solved volumetric lid model.

| Test | E | F |
|---|---:|---:|
| neutral proper crossings | 0 | 0 |
| crossings at blink .5 | 0 | 3 |
| crossings at blink .9 | 1 | 4 |
| crossings at blink 1 | 44 | 27 |
| maximum edge stretch, tested states | 1.835852 | 1.707768 |
| maximum area ratio, tested states | 3.852046 | 1.720554 |
| minimum globe surface distance, mm | 0.004057 | 0.518698 |
| full-blink admission | FAIL | FAIL |

At full closure, E has 40 lid/lid and 4 globe/lid proper crossings. F has 26 lid/lid and 1 mixed skin/lid transition crossing. `contact-ownership.json` lists semantics for every vertex, avoiding the misleading first-vertex-only category skin/skin. Unsigned surface distances are not clearance certificates when a proper crossing exists.

Both preserve neutral geometry but are worse than the historical six-contact endpoint. Neither replaces the positive neutral fixture or previous operator. No third candidate, coefficient clamp, maximum-blink reduction, threshold relaxation or post-hoc culling was used.

## Additional structural capacity gap

The frozen eye insertion has three annular bands forming ONE sheet. It has no separate inner lid wall, no positive-thickness slab, and no explicitly paired upper/lower material margins. Consequently upper/lower wall thickness is UNDEFINED, not zero and not globe clearance. No value or PASS is invented. Full-eye closure cannot be qualified against the requested wall-thickness contract with this representation as it stands.

The experiment establishes that monotone margin targets or per-vertex arc transport alone do not guarantee an injective band interpolation. The next local repair needs explicit material correspondence/contact-zone connectivity and finite wall support while preserving the existing exterior neutral reference where possible. It does not justify a full eye/nose/mouth rebuild. This is an anatomy/contact blocker, not encoder/trainer work.

## Sequencing

Identity-diverse, squint and pose qualification did not run after nominal closure rejection. Retained dynamic admission FAIL. Prepared seam remains gated and NOT_RUN. Attached jaw, full-face expressions, full anatomy and training remain blocked. V0 NO.

```sh
OPENBLAS_NUM_THREADS=1 python -m unittest experiments.v265_eyelid.test_closure experiments.v265_retained.test_contract experiments.v265_commissure.test_candidates
OPENBLAS_NUM_THREADS=1 python -m experiments.v265_eyelid.root /tmp/eyelid
OPENBLAS_NUM_THREADS=1 python -m experiments.v265_eyelid.audit /tmp/eyelid
```

All three workflows succeeded on tested code: `0570048bc81d2438d997a4b9929cfa07c82d9f80`. Scientific rejection is recorded even when CI execution succeeds.

One incoming vendor-mail search found no matching new messages since 2026-09-12. MetaHuman access and FaceVerse rights remain pending; Synthesis and 3D-Ace RFQs remain sent. No outgoing message or payment.

CI runs: eyelid 34781319492 SUCCESS; selfhost 34781321652 SUCCESS; quality contracts 34781321641 SUCCESS. Evidence-only HEAD skips CI. Explicit margin inventory: right upper/lower samples 17/19, left 16/19; no paired material correspondence or inner-wall vertices. Inventory is saved in `material-contract.json`.

Measured CI cross-runtime neutral maximum absolute difference: 3.469446951953614e-18 metres. Local same-runtime difference is 0; topology and serialized reference-byte SHA checks pass.
