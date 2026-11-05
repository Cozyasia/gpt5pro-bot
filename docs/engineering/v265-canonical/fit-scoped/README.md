# Learned-basis source fit and scoped residency checkpoint

Experimental evidence at GitHub HEAD `044f30715a0d54a42bf361934b2388c98af02a68`, canonical CI run 34307016119. No production change or L image produced.

GCV is selected on even source landmarks only. Odd landmarks are held out from both coefficient fit and regularization selection. All five independent sources improve held-out pixel RMSE (case01 9.694→4.037; case02 24.414→9.449; case04 14.878→10.506; case07 9.636→6.596; case08 9.480→4.334). Exact repeated sources return identical fit evidence.

This is NOT recovery of true canonical identity. The fit jointly adjusts learned identity/expression bases under a fixed inferred camera; it may absorb camera error or incompatible landmark definitions. Standardized parameter displacement L2 reaches 43.91. Maximum principal-angle cosines between projected identity/expression subspaces are 0.995–0.997. Strong ambiguity remains; the fit is not promoted into L or runtime. Pixel RMSE is within-case evidence, not a cross-person ranking or calibrated threshold.

Scoped memory: real application construction (47 handler groups), warmed PIPNet/MobileFace, infer source+target with L components, retain 460380 bytes of projected geometry, release model/net/detector, then three standard→strict baseline compositor cycles in the same process. Docker memory=512 MiB, swap=0. Cgroup peak 494256128 bytes (471.36 MiB), RSS high-water 499068 KiB (487.37 MiB), OOM/max events zero, stable PID and identical output hashes across repetitions. This initial experiment loads L once; the next probe reloads L before every repeated request. Neither is a full L renderer or initialized production daemon qualification.

Canonical identity, accessory ownership, mouth texture retargeting, full-resolution visibility and production memory remain unqualified. No new human sheet.
