"""Original analytic facial surface. No downloaded geometry, images, or weights.

This is a facial PATCH, not a watertight anatomical head. Nasal wings, lip/eyelid
ridges and philtrum are relief geometry; cavities are not volumetric anatomy.
Engineering/pretraining only. Identity and expression are separate additive maps.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from experiments.v265_selfhost.geometry import raster

VERSION = "original-relief-anatomy-3"
IDENTITY = (
    "width height forehead orbital_spacing eye_aperture eyelid nose_width "
    "nose_length nose_projection bridge nostril cheek maxilla mouth_width "
    "upper_lip lower_lip cupid_bow philtrum jaw_width jaw_angle chin_width "
    "chin_height chin_projection asymmetry"
).split()
EXPRESSIONS = "smile opening compression protrusion corners brow closure squint".split()
REGIONS = ["jaw", "chin", "nose", "mouth", "eyes", "cheeks", "brows"]


def surface(resolution=0):
    nx, ny = [(41, 49), (65, 81)][resolution]
    u, v = np.meshgrid(np.linspace(-1, 1, nx), np.linspace(-1, 1, ny))
    x, y = u.ravel(), v.ravel()

    def g(a, b, sx, sy):
        return np.exp(-(((x - a) / sx) ** 2) - ((y - b) / sy) ** 2)

    eye = g(-0.38, -0.22, 0.22, 0.12) + g(0.38, -0.22, 0.22, 0.12)
    mouth = g(0, 0.40, 0.36, 0.10)
    chin = g(0, 0.85, 0.4, 0.18)
    z = 0.010 * (1 - x * x) + 0.021 * g(0, 0.02, 0.17, 0.3) - 0.004 * eye
    z += 0.006 * (g(-0.48, 0.20, 0.3, 0.27) + g(0.48, 0.20, 0.3, 0.27))
    z += 0.003 * (g(0, 0.36, 0.30, 0.035) + g(0, 0.46, 0.30, 0.035)) + 0.005 * chin
    neutral = np.stack([0.075 * x * np.sqrt(1 - 0.65 * y * y), 0.105 * y, -z], 1)
    basis = np.zeros((24, len(x), 3))
    fields = [
        (0, neutral[:, 0] * 0.09),
        (1, neutral[:, 1] * 0.07),
        (2, -0.003 * g(0, -0.7, 0.8, 0.3)),
        (0, 0.003 * np.tanh(x / 0.2) * eye),
        (1, 0.002 * np.tanh((y + 0.22) / 0.05) * eye),
        (2, -0.0015 * eye),
        (0, 0.002 * np.tanh(x / 0.2) * g(0, 0.05, 0.22, 0.3)),
        (1, 0.003 * g(0, 0.1, 0.2, 0.3)),
        (2, -0.004 * g(0, 0.04, 0.16, 0.27)),
        (2, -0.002 * g(0, -0.1, 0.1, 0.25)),
        (2, -0.002 * (g(-0.17, 0.19, 0.065, 0.05) + g(0.17, 0.19, 0.065, 0.05))),
        (2, -0.003 * (g(-0.45, 0.17, 0.25, 0.25) + g(0.45, 0.17, 0.25, 0.25))),
        (2, -0.002 * g(0, 0.29, 0.42, 0.19)),
        (0, 0.004 * x * mouth / 0.36),
        (2, -0.0015 * g(0, 0.36, 0.30, 0.035)),
        (2, -0.0015 * g(0, 0.46, 0.30, 0.04)),
        (2, -0.001 * (g(-0.08, 0.35, 0.04, 0.045) + g(0.08, 0.35, 0.04, 0.045))),
        (2, 0.0015 * g(0, 0.28, 0.05, 0.09)),
        (0, 0.003 * np.tanh(x / 0.2) * g(0, 0.67, 1, 0.25)),
        (0, 0.003 * np.tanh(x / 0.2) * g(0, 0.8, 1, 0.16)),
        (0, 0.002 * x * chin),
        (1, 0.003 * chin),
        (2, -0.003 * chin),
        (2, 0.0015 * x * g(0, 0, 0.9, 0.9)),
    ]
    for k, (axis, f) in enumerate(fields):
        basis[k, :, axis] = f
    expression = np.zeros((8, len(x), 3))
    expression[0, :, 1] = -0.007 * (g(-0.3, 0.4, 0.14, 0.12) + g(0.3, 0.4, 0.14, 0.12))
    expression[1, :, 1] = 0.004 * np.tanh((y - 0.41) / 0.04) * mouth
    expression[2, :, 1] = -0.0015 * (y - 0.41) / 0.08 * mouth
    expression[3, :, 2] = -0.003 * mouth
    expression[4, :, 1] = 0.003 * x * mouth
    expression[5, :, 1] = -0.004 * (
        g(-0.38, -0.39, 0.25, 0.08) + g(0.38, -0.39, 0.25, 0.08)
    )
    expression[6, :, 1] = -0.002 * np.tanh((y + 0.22) / 0.04) * eye
    expression[7, :, 2] = -0.0015 * eye
    # Original bounded high-frequency identity detail, orthogonal to expression span.
    raw = np.zeros((12, len(x), 3))
    for k in range(12):
        raw[k, :, 2] = (
            0.00025
            * np.sin((k % 4 + 2) * np.pi * x)
            * np.cos((k // 4 + 2) * np.pi * y)
            * (1 - x * x)
            * (1 - y * y)
        )
    q = np.linalg.qr(expression.reshape(8, -1).T)[0]
    raw = (raw.reshape(12, -1) - (raw.reshape(12, -1) @ q) @ q.T).reshape(raw.shape)
    a = np.arange(nx * ny).reshape(ny, nx)[:-1, :-1].ravel()
    triangles = np.concatenate(
        [np.stack([a, a + 1, a + nx], 1), np.stack([a + 1, a + nx + 1, a + nx], 1)]
    )
    regions = np.full(len(x), 5)
    regions[y > 0.58] = 0
    regions[(y > 0.75) & (abs(x) < 0.45)] = 1
    regions[(abs(x) < 0.24) & (y > -0.35) & (y < 0.24)] = 2
    regions[(abs(x) < 0.43) & (y > 0.25) & (y < 0.55)] = 3
    regions[(abs(x) > 0.16) & (abs(x) < 0.68) & (y > -0.35) & (y < -0.09)] = 4
    regions[(abs(x) > 0.16) & (abs(x) < 0.68) & (y > -0.48) & (y <= -0.35)] = 6
    return dict(
        neutral=neutral.astype("f4"),
        basis=basis.astype("f4"),
        residual=raw.astype("f4"),
        expression=expression.astype("f4"),
        triangles=triangles.astype("i4"),
        uv=np.stack([(x + 1) / 2, (y + 1) / 2], 1).astype("f4"),
        regions=regions,
    )


def anatomy(s, c, r):
    return (
        s["neutral"]
        + np.einsum("k,knc->nc", c, s["basis"])
        + np.einsum("k,knc->nc", r, s["residual"])
    )


def expression(s, neutral, e):
    return neutral + np.einsum("k,knc->nc", e, s["expression"])


def texture(seed, size=128, accessory=0):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[-1 : 1 : complex(size), -1 : 1 : complex(size)]
    skin = np.array([0.62, 0.43, 0.34]) + rng.uniform(-0.12, 0.12, 3)
    rgb = np.broadcast_to(skin, (size, size, 3)).copy()
    labels = np.ones((size, size), np.uint8)
    rgb += 0.015 * np.sin(x[..., None] * 43 + seed) * np.cos(y[..., None] * 37)
    eyes = ((abs(x) - 0.38) / 0.18) ** 2 + ((y + 0.22) / 0.07) ** 2 < 1
    lids = (((abs(x) - 0.38) / 0.21) ** 2 + ((y + 0.22) / 0.10) ** 2 < 1) & ~eyes
    brows = (abs(abs(x) - 0.38) < 0.22) & (abs(y + 0.4) < 0.035)
    upper = (x / 0.32) ** 2 + ((y - 0.36) / 0.035) ** 2 < 1
    lower = (x / 0.32) ** 2 + ((y - 0.46) / 0.04) ** 2 < 1
    for mask, cl, col in [
        (lids, 4, skin * 0.82),
        (eyes, 3, [0.80, 0.78, 0.73]),
        (brows, 2, [0.12, 0.08, 0.06]),
        (upper, 5, [0.48, 0.20, 0.20]),
        (lower, 6, [0.54, 0.25, 0.25]),
    ]:
        labels[mask] = cl
        rgb[mask] = col
    iris = eyes & (abs(abs(x) - 0.38) < 0.045)
    rgb[iris] = [0.15, 0.20, 0.18]
    # Texture-space synthetic accessories; no assertion of physical lens modelling.
    if accessory:
        d = ((abs(x) - 0.38) / 0.26) ** 2 + ((y + 0.22) / 0.16) ** 2
        frames = (d > 0.78 if accessory == 1 else d > 0.58) & (d < 1.05)
        lens = d < 0.58
        labels[lens] = 12 if accessory == 3 else 11
        rgb[lens] *= 0.38 if accessory == 3 else 0.92
        labels[frames] = 10
        rgb[frames] = 0.045
    return rgb.clip(0, 1).astype("f4"), labels


def camera(yaw, pitch, size=64):
    a, b = np.deg2rad([yaw, pitch])
    cy, sy = np.cos(a), np.sin(a)
    cx, sx = np.cos(b), np.sin(b)
    R = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]) @ np.array(
        [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    )
    return (
        np.array([[size * 2.1, 0, size / 2], [0, size * 2.1, size / 2], [0, 0, 1]]),
        R,
        np.array([0, 0, 0.5]),
    )


def generate(out, identities=128, resolution=0, size=64):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    s = surface(resolution)
    np.savez(out / "topology.npz", **s)
    rng = np.random.default_rng(265120)
    rows = []
    start = time.monotonic()
    for i in range(identities):
        c = rng.uniform(-1, 1, 24).astype("f4")
        r = rng.uniform(-1, 1, 12).astype("f4")
        n = anatomy(s, c, r)
        split = (
            "train"
            if i < int(identities * 0.625)
            else "validation" if i < int(identities * 0.8125) else "test"
        )
        alb, _ = texture(1000 + i)
        for view in range(8):
            e = np.zeros(8, dtype="f4")
            e[[0, 0, 1, 4][view % 4]] = [0, 1, 1, -1][view % 4]
            yaw = [0, 0, 0, 0, -35, 35, -50, 50][view]
            pitch = [0, 0, 0, 0, 10, -10, 20, -20][view]
            K, R, t = camera(yaw, pitch, size)
            v = expression(s, n, e)
            tex, lab = texture(1000 + i, accessory=(view // 2) % 4)
            uv = s["uv"]
            sem = lab[(uv[:, 1] * 127).astype(int), (uv[:, 0] * 127).astype(int)]
            light = (0.85 + 0.1 * (view % 3), 0.18 * (-1) ** view, 0.1)
            render = raster(v, s["triangles"], K, R, t, size, uv, tex, sem, light)
            path = out / f"{i:04d}_{view}.npz"
            np.savez_compressed(
                path,
                rgb=render["rgb"],
                semantic=render["semantic"],
                visibility=render["visibility"],
                neutral=n,
                expressed=v,
                coefficients=c,
                residual=r,
                expression=e,
                K=K,
                R=R,
                t=t,
                albedo=alb,
                light=np.array(light),
                depth=render["depth"],
            )
            rows.append(
                dict(
                    identity=i,
                    split=split,
                    view=view,
                    path=path.name,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
        if i % 8 == 0:
            print(
                json.dumps(
                    {"generated_identities": i + 1, "seconds": time.monotonic() - start}
                ),
                flush=True,
            )
    text = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
    (out / "manifest.jsonl").write_text(text)
    report = dict(
        generator=VERSION,
        identities=identities,
        renders=len(rows),
        vertices=len(s["neutral"]),
        triangles=len(s["triangles"]),
        manifest_sha256=hashlib.sha256(text.encode()).hexdigest(),
        status="ENGINEERING_PRETRAINING_ONLY",
        commercial_training_allowed=False,
        external_assets=[],
        limitations=[
            "open facial relief patch",
            "no volumetric cavities",
            "accessories are UV decals",
            "not human anatomical validation",
        ],
    )
    (out / "provenance.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("out")
    p.add_argument("--identities", type=int, default=128)
    p.add_argument("--resolution", type=int, default=0)
    a = p.parse_args()
    print(generate(a.out, a.identities, a.resolution))
