# Offline V265 full-face transfer checkpoint

Production remains frozen at main c4bda09a98557e1bdea46338bccf66d8b6e6ed61 / Render LIVE dep-dafadhdg1s2s73dn3ggg. No experimental runtime import, merge or deploy. PR 119 builds on diagnostic PR 118. Human acceptance is absent.

## Reproducible inputs and variants

Committed public source photographs and frozen ImageGen Stage-1 bytes are in `tests/fixtures/v265_matrix`, with SHA256 and upstream source attribution. These are external ImageGen fixtures, **not production Gemini qualification**. Original image dimensions are normalized once by Lanczos4 to 1856x2304; no claim of native 2K generation. Every A-E input within a case has the same PNG hash. Source photographs are never upscaled to bypass source preflight.

Cases: 01 restaurant/warm light; 02 waterfront cafe/daylight; 04 museum/monochrome/mild head rotation. Three independent identities, three scenes, one scene per identity. Case03 was rejected by unchanged native-face guard (318.9px < 320px); its bytes remain an ineligible fixture, not a successful comparison. Multi-scene repeats of each identity and real pose/expression labels remain missing.

A = existing baseline; B = dense mask only; C = planar source core only; D = dense mask + planar source core; E = dense mask + source core with broad illumination residual. All use the existing dense correspondence, same-engine strict, monotonic ocular and final selectors. Each case stores standard, strict and selected PNGs in CI artifacts. `comparison.csv` includes both paths; quoted comparisons below use the original selector's selected path and therefore include its standard/strict choice.

## Mask ownership audit

On all three new frozen targets, actual baseline mask has jaw 0/17 and chin 0/3; lips 15/20, 12/20, 12/20. Dense support has jaw 17/17, chin 3/3, lips 20/20. Tests also check +/-25 degree roll, neck and right-side firewall exclusion. Feather is inward only for D/E; jaw boundary alpha is positive but is NOT a guarantee of strong boundary identity preservation.

Full-image rowwise verification found **zero modified pixels outside dense face support for D/E**, standard and strict on every case. A/B/C can modify pixels outside that polygon through the old blend. B's expanded-mask-only variant changes 56k-67k pixels outside dense support, so mask-only is not an acceptable no-neck solution. The neck sample itself remains unchanged in all runs; a single sample would have missed this spill. PERSON-B's entire right-side firewall is bit-exact in every output. Arbitrary overlapping PERSON-B segmentation is not proved.

Important limits: PIPNet-68 has no hairline segmentation. Forehead support uses conservative brow extrapolation, not a proven hairline boundary. Target jaw silhouette still owns the mask. Dense support does not by itself reconstruct source jaw shape or separate 3D identity from pose.

## Generator measurements (lower is better, interocular normalized)

| Case / selected mode | Nose | Mouth | Chin | Inner face |
|---|---:|---:|---:|---:|
| 01 A | .017213 | .018725 | .042776 | .020612 |
| 01 D | .015469 | .015015 | .068818 | .018606 |
| 01 E | .014505 | .012367 | .061231 | .016864 |
| 02 A | .015164 | .029547 | .065034 | .021537 |
| 02 D | .013230 | .018435 | .027027 | .014063 |
| 02 E | .017335 | .021061 | .025794 | .018145 |
| 04 A | .011197 | .016802 | .035614 | .018221 |
| 04 D | .005944 | .005683 | .011475 | .006152 |
| 04 E | .004840 | .002778 | .019971 | .005635 |

D is the best current broad candidate for human comparison: improves nose/mouth/chin together in cases02/04 and has exact outside-support preservation. E competes on case04 nose/mouth and case02 chin, but worsens case02 nose. Neither wins all cases: **case01 chin regresses**. No variant is declared visually accepted. Human sheets show source plus A/D/E; sheet labels B and C refer to D and E respectively.

Pose telemetry contains roll and nose/mouth 2D proxies only. These confound identity/expression/pose and do not establish 3D pose retention. Source core can restore source lighting too strongly. Human review of the full scenes, seams and expression is mandatory; low morphology values do not prove natural integration.

## Calibration results and remaining failures

Per-source observed maxima are fitted using 29 exact-source nuisance transforms per photograph, with no rejected candidate and no multiplier. Seven public photographs represent five identities. This is source-adaptive repeatability calibration, not population calibration from human-labelled generations. Disjoint transform parameters are evaluated after fitting; perspective proxies are not fitted or labelled as real 3D pose.

- Original mixed holdout replay: **19 PASS, 1 FAIL, 0 invalid**, versus former 7 PASS, 12 FAIL, 1 invalid.
- New isolated holdout: **101/105 PASS**, 4 false rejects using morphology + local HOG. Same-bank old gate rejects39/105.
- Per-category failures: brightness0/14, contrast0/14, color1/14, JPEG1/14, PNG0/7, resize0/14, scale1/14, roll1/14.
- Perspective proxy: 9/14 rejected; no calibrated pose/expression domain.
- Controlled morphology: mouth4/7, nose6/7, jaw/chin6/7, lower-face7/7, combined7/7 detected. **30/35 is insufficient.**
- Eye candidates: bandpass correlation, smoothed census and pooled gradient HOG, in the same global eye-line frame with no independent eye registration or patch. HOG detects aperture7/7, eyelid7/7, eye width7/7, iris-relation proxy5/7. The last stress moves central-eye pixels; no anatomical iris detector is claimed. HOG is the provisional measurement candidate, not a validated exact-fidelity veto.
- The real rejected photo3 final exceeds its source-only benign envelope in nose/mouth/chin/lower-face and all regional appearance channels. Production recognition .778736 and old geometry PASS do not override that result. Only scalars are persisted; no private derivative images were written or uploaded.

The reduced false-reject rate trades off drift recall. This subsystem stays offline until those missed negatives, expression and actual pose cases are addressed. No human-approved generated positives or cross-person calibration are added by inference.

## Memory, CI and corrections

First matrix run34133247725 at006f24b completed all three jobs, five modes each, standard+strict, 1856x2304, daemon thread, 512MiB container, 0.5 CPU, stable process. Case01 RSS was 393-440MiB. Raw cgroup peaks reached512MiB including reclaimable file cache; this is not proof of safe headroom with the complete production application baseline. D/E use ROI buffers and channelwise blends, avoiding the older N-by-3 float64 fit design matrix.

Production CI1166, Single Owner66, Analysis6 and Matrix1 passed. Strict33 had two independently diagnosed failures: a504 model download and a high-pressure test expecting completion while holding a resident bytearray, incorrectly described as reclaimable cache. The production guard correctly blocked at46MiB effective headroom versus its64MiB reserve. CI now preloads pinned models with bounded retries; resident-pressure daemon test explicitly requires controlled block at208MiB load, while the separate no-ballast daemon test still requires completion. The production guard and thresholds are unchanged. Final PR checks supersede these historical run numbers.

Local regressions:202 tests passed before final commit. Extra verification checks actual mask coverage, all outside-support pixels, PNGs, private bad-candidate scalar veto, descriptor invalid evidence and original holdout improvement. No test or CI green status constitutes human identity acceptance.

## Reproduction and human review

Run `python -m scripts.v265_matrix_prepare --case case01 --models /tmp/models --output /tmp/matrix`, then each `scripts.v265_transfer_matrix --worker --daemon --case case01 --mode MODE --models /tmp/models --output /tmp/matrix`. Repeat case02/case04. CI runs one worker at a time so a heavy Python parent does not consume part of the512MiB budget.

`human_comparison.jpg`: three rows, Source / A baseline / B mask+planar / C mask+frequency. Separate `case*_all_variants.jpg` include Stage-1, A-E crops and full scenes. No images have human acceptance labels. Required feedback is which candidate preserves this exact source face, and whether pose, seams or pasted-face appearance make any candidate unacceptable.

**Production blockers:** case01 jaw/chin regression; remaining morphology/iris stress misses; pose/expression and photorealism labels; source-relative silhouette/hairline semantics; production daemon baseline headroom; actual production-provider validation. Manual Telegram retest remains NO.

### Measured-pressure correction after Strict34

Model preloading increased reclaimable cache and reduced retained download buffers. Consequently even208MiB ballast left145-154MiB effective headroom, and the real guard correctly allowed completion. Fixed ballast is not an assertion about available memory. The CI pressure fixture now adds real resident4MiB chunks **at strict entry** until measured headroom reaches32MiB, then calls the unchanged64MiB production guard and requires its own controlled-block exception. No cgroup readings or production thresholds are mocked/changed. The no-pressure tests still require complete standard/strict execution. Earlier Strict33/34 failures are retained as evidence, not concealed by accepting either outcome.
