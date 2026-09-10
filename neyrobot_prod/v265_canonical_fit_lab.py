"""Offline learned-basis fit diagnostic. No source 2D residual is appended.

The camera is fixed; shape/expression ambiguity remains measurable. Selection
uses only source training observations, never a rejected output/human ranking.
Held-out landmarks are excluded from fitting AND regularizer selection.
"""

import numpy as np
from .v265_canonical_lab import Parameters, project, finite


def gcv_ridge(design, residual):
    a = np.asarray(design, dtype=float)
    y = np.asarray(residual, dtype=float)
    if (
        a.ndim != 2
        or y.shape != (len(a),)
        or not np.isfinite(a).all()
        or not np.isfinite(y).all()
    ):
        raise ValueError("invalid fit evidence")
    u, s, vt = np.linalg.svd(a, full_matrices=False)
    if not len(s) or s[0] <= 0:
        raise ValueError("unobservable basis")
    # Spectrum-scaled numerical search, not a per-person coefficient grid.
    lambdas = s[0] ** 2 * np.logspace(-8, 4, 97)
    uy = u.T @ y
    orthogonal = max(0.0, float(y @ y - uy @ uy))
    scores = []
    for lam in lambdas:
        h = s * s / (s * s + lam)
        scores.append(
            (orthogonal + np.sum(((1 - h) * uy) ** 2))
            / max(len(y) - h.sum(), 1e-9) ** 2
        )
    best = int(np.argmin(scores))
    lam = lambdas[best]
    delta = vt.T @ ((s / (s * s + lam)) * uy)
    return delta, {
        "lambda": float(lam),
        "gcv": float(scores[best]),
        "effective_dof": float(np.sum(s * s / (s * s + lam))),
        "search_boundary": best in (0, len(lambdas) - 1),
        "singular_values": s.tolist(),
    }


def fit_source_diagnostic(model, source, roi, observed, coefficient_std):
    obs = finite(observed, (68, 2)).astype(float)
    prior = np.r_[source.identity, source.expression].astype(float)
    std = finite(coefficient_std, (50,)).astype(float)
    if np.any(std <= 0):
        raise ValueError("invalid learned parameter scale")
    indices = model.landmarks
    xyz = model.shape(source.identity, source.expression)[indices]
    base = project(xyz, source.camera, roi)[:, :2].astype(float)
    basis = np.concatenate(
        (model.identity_basis[indices], model.expression_basis[indices]), axis=2
    ).astype(float)
    camera = source.camera[:2, :3].astype(float).copy()
    camera[0] *= (roi[2] - roi[0]) / 120
    camera[1] *= -(roi[3] - roi[1]) / 120
    design = np.einsum("dc,vck->vdk", camera, basis) * std
    # Interleaving holds out entire 2D landmarks, not one coordinate of each.
    train = np.arange(0, 68, 2)
    holdout = np.arange(1, 68, 2)
    delta, info = gcv_ridge(design[train].reshape(-1, 50), (obs - base)[train].ravel())
    values = prior + delta * std
    fitted = Parameters(
        source.camera.copy(),
        values[:40].astype(np.float32),
        values[40:].astype(np.float32),
    )
    prediction = project(
        model.shape(fitted.identity, fitted.expression)[indices], fitted.camera, roi
    )[:, :2]
    rmse = lambda x: float(np.sqrt(np.mean(x * x)))
    info.update(
        train_landmarks=train.tolist(),
        heldout_landmarks=holdout.tolist(),
        heldout_before_px=rmse((base - obs)[holdout]),
        heldout_after_px=rmse((prediction - obs)[holdout]),
        train_before_px=rmse((base - obs)[train]),
        train_after_px=rmse((prediction - obs)[train]),
        parameter_step_std_l2=float(np.linalg.norm(delta)),
        production_qualified=False,
        identity_expression_separation_proven=False,
    )
    info["heldout_improved"] = info["heldout_after_px"] < info["heldout_before_px"]

    # Principal-angle evidence: projection may make identity and expression
    # subspaces indistinguishable even though coefficient arrays are separate.
    def observable_space(a):
        u, singular, _ = np.linalg.svd(a, full_matrices=False)
        rank = (
            int(
                np.count_nonzero(
                    singular > singular[0] * max(a.shape) * np.finfo(float).eps
                )
            )
            if len(singular) and singular[0] > 0
            else 0
        )
        return u[:, :rank]

    qa = observable_space(design[train, :, :40].reshape(-1, 40))
    qb = observable_space(design[train, :, 40:].reshape(-1, 10))
    info["identity_observable_rank"] = qa.shape[1]
    info["expression_observable_rank"] = qb.shape[1]
    info["identity_expression_subspace_cosines"] = np.linalg.svd(
        qa.T @ qb, compute_uv=False
    ).tolist()
    return fitted, info
