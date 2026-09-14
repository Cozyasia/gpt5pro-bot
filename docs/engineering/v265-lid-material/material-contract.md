# Lid material contract and rejected neutral construction

Status: EXPERIMENTAL / NOT ADMITTED. Frozen exterior reference, mouth D2, corotated expressions, nose V2, old blink and rejected E/F fixtures are untouched. No blink, seam, training, real matrix, merge or deploy in this cycle.

## Material coordinates and ownership

For each eye, the frozen 3-band exterior insertion is the outer material surface. The 36-sample right and 35-sample left aperture cycles are split at the two neutral x extrema (identity-owned canthi) into upper and lower material paths. Path coordinates u run monotonically from 0 to 1 by neutral arc length. `material_domains` in neutral.json supplies all exterior/inner vertex IDs, triangles, path u values and canthus IDs. Upper/lower correspondence is defined by equal normalized material u using piecewise-linear interpolation, rather than pretending unequal vertex counts form one-to-one pairs. This is an explicit initial material contract, not an established anatomical correspondence.

The inner-wall candidate duplicates all exterior insertion vertices, including its orbital rim, at +0.1 mm in the local posterior direction. Inner faces reverse winding. Two triangles per aperture edge connect outer and inner margins into a finite margin band. The orbital inner rim remains an explicit open attachment boundary: capping it against the already-attached outer skin would create triple-edge topology. Canthi retain separate neighboring material vertices and finite connectors; none is collapsed. Globes remain separate closed rigid components, unchanged.

Prospective full-blink contact is limited to corresponding upper/lower margin bands, with opposed normals, no volume penetration, and no contact outside those IDs. No closure operator or contact PASS is implemented because neutral construction fails. Full contact-zone mechanics must be validated only after neutral wall and clearance admission.

## Neutral construction and stop decision

The candidate has 5,528 vertices and 10,664 triangles. Exterior original vertices and triangles are bit-exact; all changes are appended inner-wall/connector geometry. The boundary cycles are 256 / 61 / 36 / 35 edges (outer face, reserved mouth, and orbital inner rims). No new external face/model assets were used.

Measured neutral result:

| Metric | Result |
|---|---:|
| Exterior deviation | 0 m, bit-exact |
| Proper intersections | 40 |
| Exterior/inner-wall pairs | 40 |
| Positive-area coplanar overlaps | 0 |
| Non-manifold edges | 0 |
| Winding defects | 0 |
| Degenerate triangles | 0 |
| Duplicate faces | 0 |
| Neutral admission | FAIL |

| Globe surface distance | Frozen exterior | New wall candidate |
|---|---:|---:|
| Right | 0.527095 mm | 0.450353 mm |
| Left | 0.588009 mm | 0.510060 mm |

This candidate violates both contact validity and the unchanged neutral clearance envelope. No lower clearance was authorized or substituted. Nominal 0.1 mm coordinate displacement is NOT finite wall-thickness qualification. The unsigned distance routine returns small positive values even for these intersecting sets; those numbers must not be represented as valid thickness. The actual surface separation is zero at proper crossing witnesses. The corrected validator requires structural validity before positive-wall admission.

All 40 exact triangle pairs, vertex IDs and coordinates are in contact-map.json. This result rejects uniform posterior extrusion. It does not prove that every material construction preserving the exterior is impossible; therefore no exterior-coordinate modification is justified or performed here. No amplitude/offset sweep, E/F tuning, threshold relaxation or culling followed the failure.

As explicitly requested: neutral FAIL stops the chain. Dense blink, calibration/sealed dynamic set, identity diversity, squint/pose, seam and training are NOT_RUN. Mouth/nose fixtures remain positive and unchanged.

## Reproduction

```sh
OPENBLAS_NUM_THREADS=1 python -m unittest experiments.v265_lid_material.test_neutral experiments.v265_retained.test_contract
OPENBLAS_NUM_THREADS=1 python -m experiments.v265_lid_material.admission /tmp/lid-material
```

Code SHA: 1893c4e5a4c32593a4f9f79ebc5983826d4dfb3b. Local four tests pass. Successful CI reports execution/regression correctness, not neutral admission.

One incoming mail search found no new matching vendor responses since 2026-09-12. MetaHuman/FaceVerse pending; Synthesis/3D-Ace sent. No outgoing follow-up or financial commitment. Production main remains frozen at c4bda09a98557e1bdea46338bccf66d8b6e6ed61.

CI on tested code: lid-material 34781889075 SUCCESS; selfhost 34781892346 SUCCESS; quality contracts 34781892353 SUCCESS. Final evidence-only commit skips CI.
