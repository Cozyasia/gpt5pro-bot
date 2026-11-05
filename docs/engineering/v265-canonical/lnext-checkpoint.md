# L-next machine checkpoint — 2026-09-09

Experimental only. Production main remains
`c4bda09a98557e1bdea46338bccf66d8b6e6ed61`. No merge/deploy/human sheet.

Run: GitHub Actions `34386713919`, artifact `10118271883`. The first attempt
(`34385919502`) failed during case08 after full-frame accessory temporaries;
ROI-bounded rerun completed all seven cases in 512 MiB with swap disabled.

## Critical target-only pixels at 256 sample resolution

| case | total | forehead | brows | eyes | nose | cheeks | upper lip | lower lip | mouth interior | jaw | chin |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 01 | 1158 | 154 | 387 | 275 | 68 | 274 | 0 | 0 | 0* | 0 | 0 |
| 02 | 519 | 36 | 121 | 26 | 114 | 222 | 0 | 0 | 0* | 0 | 0 |
| 04 | 195 | 0 | 9 | 58 | 18 | 110 | 0 | 0 | 0* | 0 | 0 |
| 05 | 1189 | 154 | 358 | 304 | 69 | 304 | 0 | 0 | 0* | 0 | 0 |
| 06 | 569 | 82 | 120 | 34 | 114 | 219 | 0 | 0 | 0* | 0 | 0 |
| 07 | 333 | 2 | 63 | 50 | 27 | 191 | 0 | 0 | 0* | 0 | 0 |
| 08 | 249 | 0 | 53 | 162 | 13 | 21 | 0 | 0 | 0* | 0 | 0 |

`*` Mouth interior is explicitly target-expression-owned, not source-owned:
250/187/290/275/242/332/294 pixels for cases01/02/04/05/06/07/08.
This is not identity-complete until compatible mouth appearance is synthesized.
Unknown counts outside mesh face support are 45469/45168/44676/43545/44175/
39980/44173 and are not counted as critical face pixels.

## Triangle path

All cases have 76,073 triangles, zero degenerate triangles, zero inverted
*visible* triangles after cull, and `foldover=false`. This does not pass full
render: target-face holes remain 154/94/424/8/172/21/64 pixels. Orientation
reversals rejected before rasterization are 130/517/204/218/664/285/393.
Maximum local stretch is 356.14/13964.10/1621.31/992.88/143.86/4003.72/
2236.85; minimum compression is .000555/.000810/.001756/.001744/.000650/
.001984/.000206. These extremes are not acceptable deformation quality.

Case06 therefore has a completed cull-first raster pass and no visible
foldover, but it is **not** a successful full render: 172 uncovered face pixels,
664 rejected orientation reversals, 143.86 maximum stretch and .000650 minimum
compression.

## Accessory ownership

The landmark-bounded dark-edge hypothesis reports glasses present for all seven
sources and all seven targets, including known non-glasses controls. It does not
discriminate spectacles from eyes/brows/texture and is rejected as verified
segmentation. Its deterministic policy and bit-exact target-layer firewall are
useful contracts, but case07 remains accessory-unsafe. Do not tune its threshold
on this matrix and call it validation; the next implementation requires a real
face-parsing/accessory model or independent holdout evidence.

## Mouth decomposition

Source intrinsic and target expression descriptors are recorded for every case.
Source intrinsic geometry misses its engineering bound in all seven cases.
Target expression passes only case04; case08 fails (opening error .06544,
stretch error .07326, and mouth texture compatibility remains false). This
establishes that the current 40-identity/10-expression affine 3DMM inference does
not provide sufficient exact-photo mouth identity/expression separation.

## Memory

- Seven-case process peak RSS: 452,840 KiB (442.23 MiB).
- Canonical arrays: 24,392,528 bytes; ONNX regressor: 3,389,923 bytes.
- Retained triangle raster arrays: maximum 1,200,722 bytes.
- Isolated production-size ownership sampler cgroup peak: 105,115,648 bytes;
  RSS 123,856 KiB; swap zero; OOM events zero.
- Constructed application + warmed PIPNet/MobileFace + scoped L components +
  three standard/strict cycles: cgroup peak 497,020,928 bytes (474.00 MiB),
  RSS peak 493,364 KiB (481.80 MiB), memory.max 512 MiB, swap zero, OOM/max
  events zero. This still omits a qualified complete L image renderer and live
  Telegram history, so production memory remains unqualified.

All eight workflows on experimental HEAD are green. Green means execution and
regression integrity only; machine prequalification is false.

IDENTITY COMPLETE = NO

CASE06 FULL RENDER = NO

CASE07 ACCESSORY SAFE = NO

CASE08 TARGET EXPRESSION PRESERVED = NO

CANONICAL L MACHINE PREQUALIFIED = NO

GENERATOR QUALITY READY FOR HUMAN A/B = NO

PRODUCTION MEMORY QUALIFIED = NO

READY FOR USER MANUAL RETEST = NO
