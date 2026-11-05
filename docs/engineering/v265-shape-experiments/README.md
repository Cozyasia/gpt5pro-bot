# V265 shape ownership experiments after human review

**Experimental only. No merge/deploy. No human-approved generated output.**

Production was checked through Render: LIVE dep-dafadhdg1s2s73dn3ggg at c4bda09a98557e1bdea46338bccf66d8b6e6ed61. PR119 remains draft. All six workflows on prior HEAD712bf4b succeeded, including Production1169 and Matrix4. New-head CI must be checked separately.

## Human evidence and metric disagreement

The user's review is stored in `tests/fixtures/v265_matrix/human_review_2026-09-07.json`: case01 A preferred; case02 D provisional; case04 A preferred; none approved. These labels are not fitted as thresholds.

Case01 A preserves configuration measurements better than D: source/A/D jaw width1.86555/1.81634/1.74533, mouth-to-chin.78633/.78371/.74942, jaw-to-chin-width3.23183/3.17550/3.10851. Case04 source/A/D jaw asymmetry is -.25119/-.24244/-.23063. Thus region-averaged errors omit useful directional and relational information. These observations partially support the feedback, not a complete explanation of perceived identity. PIPNet68 does not measure cheek/chin surface volume, shading shape, or all eyelid/iris detail. D's better regional numbers cannot establish better overall identity.

An audit correction: pose_left/center/right filenames are pose examples, not documented same-identity labels. The earlier claim of seven photos/five identities was unsupported and is withdrawn. They must not become genuine same-person pose positives.

## Implemented geometry ablations

All variants use exactly one frozen Stage-1 per case, original V265 owner, ocular and final selectors. No runtime wiring or independent eye patches.

- T: D with an interpolating thin-plate inverse field, unchanged desired geometry.
- F: D plus source jaw/chin residuals lifted with a generic 3D depth template and projected under estimated target pose; exact inverse field; support follows the new jaw.
- G: F plus projected source nose and a bounded mouth-expression model. Width and lip offsets are retained; opening/corner-height changes are bounded in mouth coordinates. This cannot synthesize newly exposed teeth or fully disentangle expression.
- H: F plus target-jaw boundary/context transport over the union of old/new supports, then source core over the new support. This distinguishes moving source support from removing the old silhouette. It still uses conservative inward feather and is not a validated segmentation/occlusion solution.

OpenSeeFace's BSD-2-Clause geometry template is attributed with source-file hash and license. It is a generic depth prior, not recovered identity depth. Mouth mapping from66 to68 landmarks includes inferred inner corners. Pose is fitted to internal anchors, excluding jaw and moving lips; nose identity still confounds the estimate. Known-camera synthetic tests verify the implementation under that prior, not correctness on real faces.

TPS operates in48-row blocks, checks inverse-map Jacobian sign, and rejects folded fields. T/F/G/H run only in an offline context manager that restores all patched helpers on exit, including exceptions.

## Results: no new universal winner

Selected candidates from standard/strict; direct eye-line morphology errors below are **not pose-normalized 3D truth**.

| Case / variant | Nose | Mouth | Chin | Inner face |
|---|---:|---:|---:|---:|
|01 A|.017213|.018725|.042776|.020612|
|01 D|.015469|.015015|.068818|.018606|
|01 T|.013203|.012909|.065329|.016962|
|01 F|.011454|.007544|.079558|.016812|
|01 H|.009978|.009175|.080994|.016543|
|02 A|.015164|.029547|.065034|.021537|
|02 D|.013230|.018435|.027027|.014063|
|02 T|.010216|.014785|.045367|.012009|
|02 F|.015015|.015136|.047503|.018325|
|02 G|.030238|.048343|.012309|.029122|
|02 H|.011757|.015728|.036827|.013274|
|04 A|.011197|.016802|.035614|.018221|
|04 D|.005944|.005683|.011475|.006152|
|04 T|.005490|.003253|.012026|.005157|
|04 F|.012114|.008072|.041839|.009907|
|04 G|.025204|.023220|.053849|.019315|
|04 H|.011869|.009820|.040219|.010656|

G case01 was geometrically rejected before output because its inverse field folded. The batch workflow records this as a rejection, never a successful image. The other17 processes completed standard+strict, with stable PID, exact PERSON-B firewall, unchanged neck sample and zero changes outside their declared support for T/F/G/H. A neck sample is not full semantic neck segmentation. H's union support changes the ownership contract and remains unqualified.

The hypothesis that Gaussian averaging is the dominant jaw failure is **not supported** by measurement: production Gaussian mean control error .071–.121px, maximum .927–1.394px, chin mean .067–.116px. TPS improves interpolation error to ~1e-12px but does not solve visual identity. See `correspondence.json`.

F/H fail the case01 chin objective; G improves one chin while degrading nose/mouth. The 3D-template approach is therefore not promoted. T is a useful correspondence control, not a human-approved replacement. [Diagnostic source/A/T/H sheet, with face crops and full scenes](shape_diagnostic_comparison.jpg) documents the failed search; no new human approval is requested for these variants.

## Fidelity experiments

All limits use only29 exact-source nuisance transforms per source, without a fitted multiplier or recognition veto. The repeatedly inspected bank is now a development benchmark, not fresh independent qualification data.

| Evidence on original landmark pipeline | Benign isolated PASS | Morphology detection | Eye stress detection |
|---|---:|---:|---:|
|Existing morphology + HOG|101/105|30/35|26/28|
|Add central-eye cumulative profiles|101/105|30/35|27/28|
|Also independent relational vetoes|93/105|34/35|27/28|

Central-eye dark-band profiles retain sub-cell displacement that pooled HOG can lose. They use the fixed global eye frame, with no iris-local alignment or image patch. Bohr's iris-proxy miss is recovered. The remaining pose_left iris proxy is below its nuisance envelope (left HOG.91x; right profile.76x); its nose stress is also below every measured channel (nose morphology.26x; nose HOG.60x; nose width.36x). These misses are not repaired by moving the threshold below the rejected examples.

Relational vetoes recover mouth7/7 and jaw/chin7/7 but introduce false rejects: brightness1, contrast1, color2, JPEG1, scale5, roll2. A joint RMS-normalized configuration experiment retained101/105 benign but detected32/35 morphology; covariance whitening did not solve the tradeoff. No relational hard veto is selected.

A separate detector-scale median-box experiment replaces the discontinuous largest-box choice only for measurement. It produced99/105 benign,31/35 morphology and27/28 eye detection; adding relational vetoes worsened benign to81/105. It is retained as a negative diagnostic ablation, not a new default. Full scalar calibration rows and source-only limits are stored here.

Real same-identity yaw/pitch/expression calibration and a fresh holdout are still missing. Synthetic known-camera tests and perspective proxies do not satisfy that requirement. Perspective proxy rejects remain9/14 on the original measurement path.

## Memory and stability

Local1856x2304 workers ran on a shared host, not inside a512MiB cgroup. Per-worker RSS is in `matrix-summary.json`; isolated process figures cannot qualify production.

A new probe constructs the real `main.build_application()` with47 handler groups and retains it during the daemon-thread standard/strict worker. It blocks network calls and uses dummy credentials. T case01 peaked472.3MiB RSS, compared with426.5MiB in the earlier isolated worker. This does not include Telegram initialization, warmed live request history, or all on-demand provider models.

Read-only Render metrics returned436240400 bytes (~416.0MiB) memory usage and536870900 bytes limit over the returned21:43–22:43UTC interval, with one instance. The metric's difference is not the guard's effective headroom; reclaimable memory and cached models must be measured in context. No experimental production instrumentation was deployed. Full warmed-daemon memory qualification remains NO.

## Remaining work

210 local tests pass, including known-camera residual projection, expression width preservation, TPS correspondence, eye-profile displacement, invalid evidence and context-manager restoration. Original runtime/owner/selector code is unchanged. New workflow green means experiments executed and controlled rejections were recorded; it does not mean generator or fidelity acceptance.

The next generator step must address real-pose geometry and silhouette/occlusion uncertainty, rather than increase core strength. The repeated-identity multi-scene matrix was not expanded in this iteration; current three-case geometry failures remain unresolved. No new source was upscaled for preflight. No private images were added.

GENERATOR QUALITY READY FOR HUMAN A/B = NO
FIDELITY GATE CALIBRATED = NO
PRODUCTION MEMORY QUALIFIED = NO
READY FOR USER MANUAL RETEST = NO
