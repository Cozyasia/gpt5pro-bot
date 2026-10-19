# V265 source fidelity: independent audit and offline experiments

Status: **NOT production accepted. Do not merge or deploy this diagnostic branch.**

## Verified external state

- Repository: Cozyasia/gpt5pro-bot.
- main: c4bda09a98557e1bdea46338bccf66d8b6e6ed61.
- Render service srv-d3iofgp5pdvs7394e8rg, LIVE dep-dafadhdg1s2s73dn3ggg at the same SHA.
- Render auto-deploy remains enabled for main; freeze means no merge/push to main, not a disabled service.
- PR 118 is open/draft at initial audit; original head 8f1805005e97368a7810c65524d0df02104cdf10.
- Original Production CI 1164 failed one of 183 tests: a source-string assertion matched `threshold` in a docstring.
- Original Analysis 4 succeeded, but its only job downloaded models/fixtures. It did not execute calibration.
- Production request log at 2026-09-07 12:06:25 confirmed standard_post_ocular, identity 0.778736, strict_not_proven_better, PID 64 at start/end.

## Execution graph and safety

`sitecustomize` -> V246 compatibility bootstrap -> V265 single owner -> YuNet/model preflight -> standard transfer -> ocular before/after measurement and monotonic selection -> optional same-engine strict with memory preflight -> final selection -> PNG original document.

V253/V256/V263 remain imported as utilities. There is no runtime V262/V263/V264 recovery in the V265 owner. The new experiments are not called from `transfer_attempt` or any production gate. Ocular selector, standard/strict selector, memory guard, firewall and delivery code are unchanged.

Important precision: ocular selection forbids componentwise regression (epsilon 1e-6); final strict selection is an identity/score plus bounded-geometry rule, NOT a universal componentwise Pareto guarantee. We preserve its existing behavior. PERSON-B protection is the existing right-side pixel firewall; these tests do not prove arbitrary PERSON-B overlap left of that firewall.

## Root cause supported by code

1. `_mobileface_embedding` independently constructs each image's five alignment points from PIPNet, estimates a similarity with LMEDS, warps to 112x112 and embeds. This is recognition evidence, not an exact morphology measurement.
2. `_quality_metrics` compares final landmarks to `desired_dense`, not source. Desired geometry is projected source plus bounded target-dependent shifts: standard outline weight .26, nose .055, mouth .060; strict weights are smaller. The geometry test therefore tolerates some inherited target shape by construction.
3. Standard uses Poisson integration plus additive source bands (.38 structure, .74 detail). Poisson transfers source gradients, so calling its output simply "synthetic target pixels" would overstate the finding. Nevertheless, it has target boundary conditions, and additive bands do not guarantee source low-frequency structure. Strict adds a bounded source core; standard does not.
4. **The primary anatomy mask excludes jaw/chin and part of the mouth.** On the attached delivered frame, all 17 outline points and all three central chin points sampled zero mask support. Some lower-lip/corner points also sampled zero. This mask was reconstructed on the delivered frame, not the missing original Stage-1 frame; the exact production mask cannot be recovered from the attachment alone. Its source-code construction ends at mouth midpoint + 0.10 face height, capped at bbox y + .84 height. Stronger core inside this mask cannot fix excluded regions.
5. The production acceptance flag in `__init__.py` still says True despite human revocation. We leave production/version routing unchanged during freeze; this stale flag is not evidence of acceptance.

## Reproduced private failure (scalars/hashes only)

Exact pinned production YuNet, PIPNet and MobileFace hashes were verified. OpenCV 4.10.0.84 was used.

| Channel | Independent measurement |
|---|---:|
| MobileFace/PIPNet cosine | .7857398987 |
| eye-line normalized all68 | .0538607176 |
| inner face | .0408948255 |
| mouth | .0557324392 |
| chin | .1363373568 |
| nose | .0255283272 |
| eyes | .0034345049 |

These reproduce the earlier diagnostic measurements. The attachment measurement is not substituted for the exact production cosine .778736.

## Calibration experiment and failure to generalize

`v265_source_fidelity.py` measures morphology in one global eye-line frame plus eye appearance and gradients in fixed rectangles. It removes only photometric gain/bias/planar illumination; it never separately registers or patches eyes. Invalid or missing evidence raises, never PASS.

Thresholds for this experiment are observed per-channel maxima from 15 benign variants of three public sources (three identities); no multiplier or rejected candidate is used in fitting. Twenty benign variants of four other photos (two identities) are held out. The variants cover uniform scale, roll and brightness; they do NOT constitute yaw/expression adaptation validation.

Results stored in `tests/fixtures/v265_source_fidelity_audit.json`:

- Current human-rejected image exceeds independent public thresholds in mouth, nose, chin, lower face, outline and other channels.
- Training benign: 15/15 within envelope (in-sample, not generalization evidence).
- Held-out benign: 7 within envelope, 12 exceed, 1 unavailable. **Qualification FAIL.**
- Controlled drift: 40 exceed, 2 unavailable, from 42 trials across mouth/nose/jaw/lower face/eyes/combined. Unavailable is not a measured rejection.
- Cross-person: both eye appearance measurements unavailable; no cross-person measured-rejection claim.
- Human-approved generated positives: zero.

The eye appearance prototype remains alignment-sensitive; its excess does not yet distinguish eye identity drift reliably from detection/resampling noise. Do not tune the limits to the held-out failures and call the same set independent validation. Next calibration needs source-conditioned repeatability, pose/visibility domains and fresh independent holdout identities.

## Transfer ablation

Two unused helpers were added to the existing dense68 engine:

- `_source_core_compose_roi_experiment`: source spatial structure + target global chroma/planar luminance + boundary feather. No additive double-counted source detail over Poisson.
- `_dense_anatomy_mask_experiment`: support bounded by dense jaw and brows, with existing right-side firewall. This is not yet an occlusion/silhouette solution.

The public ablation script reuses the existing 1856x2304 probe scaffold, exact production transfer, ocular selector and both standard/strict paths. It scopes helper substitutions to the offline process and restores them. Same-source target resampling is **not a generated positive**. Scalar results are in `tests/fixtures/v265_source_core_ablation.json`.

Standard comparison, selected pre/post phase as decided by the unchanged ocular selector:

| Measurement | Baseline | Source core + dense mask |
|---|---:|---:|
| cosine (diagnostic) | .759247 | .922420 |
| direct inner face | .013081 | .010871 |
| direct mouth | .012997 | .008889 |
| direct nose | .011383 | .004595 |
| direct chin | .034925 | .026829 |
| direct lower face | .021805 | .015706 |

All six executions completed, old geometry gate passed, and right-side pixels were identical. Peak process RSS was about 474 MiB in this local sequential ablation; **this is not a Render 512 MiB production memory qualification** (bot overhead/concurrency/headroom remain unproven). Source-core-only improved recognition while some morphology worsened: another reason not to select by cosine alone.

## Blockers and continuation

- Generalizable calibrated gate is NOT established; current simple eye-line/appearance envelope fails held-out benign cases.
- Need exact saved Stage-1 bytes for the rejected request (plus exact source input if it differs from attachment); the delivered result is already composited and cannot serve as a faithful Stage-1 replay.
- Pose, expression and occlusion need a validated correspondence/measurement domain; a generic 2D similarity is not proof of yaw/pitch invariance.
- Need a private multi-source/multi-scene generated A/B matrix and human labels. No human acceptance was invented.
- No merge, Render mutation, production instrumentation, Telegram request or private image upload was performed.
- Private attachments remain user-owned originals; no derivative private images were written. Persistent regression stores scalars/hashes only.

READY FOR NORMAL USER TRAFFIC = NO

READY FOR USER MANUAL RETEST = NO
