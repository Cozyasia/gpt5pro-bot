# Offline orthographic shape checkpoint

Production remains frozen at c4bda09a98557e1bdea46338bccf66d8b6e6ed61. No compositor or fidelity experiment is connected to production. No generated output has human production approval.

## Geometry implementation

I replaces F's assumed image-camera intrinsics with a scaled-orthographic camera fitted to internal landmarks. Source-specific XY shape is recovered at the generic template's depth planes, projected under the target camera, and anchored to the target eye line. Jaw/chin controls and their support follow this projected source shape. K additionally transports the old target silhouette/context over the union of old/new supports. J adds the bounded nose/mouth strategy used by G.

This removes dependence on arbitrary image-canvas principal point and focal-length assumptions. It does **not** recover subject-specific depth or prove pose/expression disentanglement on real photographs. A known weak-perspective synthetic fixture verifies jaw residual projection and independent source/target canvas translations. The six-parameter damped Gauss-Newton solver uses NumPy/OpenCV, avoiding the extra scipy.optimize import in the worker. Folded inverse fields remain rejected.

## Same-byte comparison at 1856 x 2304

Every variant uses the existing frozen Stage-1 bytes for its case. These are production-size transfers, not new production-provider generations. Source images were not enlarged to pass preflight. Full scalar reports include standard/strict candidates, source-relative configuration, support checks, runtime and selected path. The errors below use eye-line normalization; they are not pose-invariant identity truth.

| Case / variant | Nose | Mouth | Chin | Inner face |
|---|---:|---:|---:|---:|
|01 A|.017213|.018725|.042776|.020612|
|01 D|.015469|.015015|.068818|.018606|
|01 I|.011730|.010709|.056487|.016525|
|01 K|.013722|.012479|.060998|.017627|
|02 A|.015164|.029547|.065034|.021537|
|02 D|.013230|.018435|.027027|.014063|
|02 I|.011128|.021427|.014308|.014344|
|02 K|.013827|.018646|.022871|.015510|
|04 A|.011197|.016802|.035614|.018221|
|04 D|.005944|.005683|.011475|.006152|
|04 I|.011658|.010409|.047040|.011084|
|04 K|.010296|.009029|.052168|.010904|

Eight of nine I/J/K case workers produced candidates; J case01 rejected a folded field. I is a plausible case02 candidate, not a universal winner: case01 chin improves relative to D but remains worse than A; case04 chin also regresses relative to A. J worsens nose/mouth and is not shortlisted. Case02 I/K eye-line roll differences from target are .027/.213 degrees; this does not independently qualify yaw/pitch retention. Case04 differences remain approximately four degrees.

[Case02 review: source, baseline A, previous provisional D, new I and K; face crops and full scenes](case02_orthographic_review.jpg). Only two new variants are submitted. Human feedback must assess overall identity, pose/expression, jaw/chin, eyes, seams and lighting; no acceptance label is inferred from metrics or the author's visual inspection.

## Memory evidence

The previous published b246144 workflow completed all seven workflows successfully. Its application-memory jobs construct real main.build_application() with 47 handler groups, retain warmed PIPNet/MobileFace caches, and perform three standard/strict daemon-worker repetitions inside 512 MiB / 0.5 CPU containers. Network is blocked and credentials are dummy. Actual artifact ledgers are in application-ci-b246144.json.

| Variant | Peak RSS | Effective strict-preflight headroom |
|---|---:|---:|
|A|451.3 MiB|97.70–113.77 MiB|
|T|430.4–446.7 MiB|119.74–152.13 MiB|
|H|437.5–438.8 MiB|117.05–124.24 MiB|

All nine repeated workers completed both passes with stable process IDs. Effective headroom follows the unchanged production guard's capped reclaimable-memory calculation, not simply limit minus RSS. The reserve remains 64 MiB.

New I/J/K local isolated workers peak 403.4–455.8 MiB. These local figures are not cgroup qualification. The workflow now also runs I/K with the constructed, warmed application. Telegram initialization, live request history and other lazy provider state remain absent, so even successful constructed-application jobs cannot establish full production daemon qualification.

## Fidelity and remaining blockers

No thresholds were changed to fit these candidates. Existing morphology plus HOG and the additional eye-profile channel retains 101/105 benign, detects 30/35 morphology and 27/28 eye stresses. Independent relational vetoes reach 34/35 morphology but reduce benign to 93/105. Neither meets the joint qualification target; the repeatedly inspected bank is development data, not a fresh holdout. The profile channel recovers one iris-proxy miss; pose_left's remaining iris/nose stresses remain within its nuisance envelope. Occlusion is a hypothesis, not grounds to remove those failures from the denominator.

Real same-identity pose/expression calibration, the expanded repeated-identity multi-scene matrix, a fresh holdout, and full daemon qualification remain unfinished. No new identity count is claimed. Previously named pose_left/center/right fixtures are not a verified same-person sequence. The old claim of five independent identities remains withdrawn.

GENERATOR QUALITY READY FOR HUMAN A/B = YES (case02 I/K only; no universal replacement)

FIDELITY GATE CALIBRATED = NO

PRODUCTION MEMORY QUALIFIED = NO

READY FOR USER MANUAL RETEST = NO
