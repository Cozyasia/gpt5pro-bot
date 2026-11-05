# Negative checkpoint: 2D residual does not generalize

Experimental only. No production approval, merge, deployment or runtime default.
Five public identities, seven cases, identical frozen Stage-1 bytes per case.
26 of 28 A/D/I/K workers produced images; produced does not mean acceptable.

Permanent regression roles:
- case02: human preference I > K > D > A; no production approval.
- case01/case04: human preferred A; I chin worse than A.
- case05: repeated case01 source, different scene; I chin regression.
- case06: repeated case02 source; I/K active deformation foldover rejected.
- case07: I/K stretch glasses/eye region despite passing active Jacobian check.
- case08: broad source smile copied over closed-lip Stage-1 expression.

The JPG sheets contain public fixtures only. JSON contains measured scalars;
the manifest records source/Stage-1 provenance and hashes. Requested pose angles
are generation prompts, not measured pose ground truth. Generated scenes are
not genuine same-person pose/expression calibration photos.

The common TPS domain fixes inconsistent boundary anchors between full-face and
ocular ROIs. It does not solve identity/expression decomposition, visibility,
accessory ownership or excessive non-inverting distortion. Adaptive jackknife
shrinkage modestly improves case01 but worsens case02; it is not a new default.

Local test run at checkpoint: 213 passed. New revision remote CI not yet run.
Full production daemon memory qualification remains absent. A 64 MiB resident
pressure scenario is prepared, not a measurement of live daemon history.

I/K are frozen negative/control references. Next experiments must replace the
entangled representation, not tune per-case residual strengths.
