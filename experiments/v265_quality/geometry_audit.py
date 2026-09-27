"""Resolution capacity and controlled geometry stress, without invalid-face culling."""

import json, time
from pathlib import Path
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from experiments.v265_quality.factory import (
    surface,
    anatomy,
    expression,
    camera,
    texture,
)
from experiments.v265_selfhost.geometry import raster
from experiments.v265_prior.evaluate import topology_metrics


def audit(out):
    rng = np.random.default_rng(990)
    rows = []
    high = surface(1)
    for level in (0, 1):
        rng = np.random.default_rng(990)
        s = surface(level)
        n = 0
        lo = 1e9
        hi = 0
        edge = 0
        times = []
        capacity = []
        for i in range(32):
            c = rng.uniform(-1, 1, 24)
            r = rng.uniform(-1, 1, 12)
            e = rng.uniform(-1, 1, 8)
            v = anatomy(s, c, r)
            target = expression(s, v, e)
            m = topology_metrics(target, s["neutral"], s["triangles"])
            n += m["orientation_failures"]
            lo = min(lo, m["local_area_ratio"]["min"])
            hi = max(hi, m["local_area_ratio"]["max"])
            edge = max(edge, m["edge_stretch"]["max"])
            if level == 0:
                interpolator = RegularGridInterpolator(
                    (np.linspace(-1, 1, 49), np.linspace(-1, 1, 41)),
                    v.reshape(49, 41, 3),
                )
                dense = interpolator(high["uv"][:, [1, 0]] * 2 - 1)
                gt = anatomy(high, c, r)
                capacity.append(
                    float(np.sqrt(np.mean(np.sum((dense - gt) ** 2, axis=1))) * 1000)
                )
            if i < 4:
                K, R, t = camera([-65, -40, 40, 65][i], [-25, 25, -25, 25][i])
                tex, _ = texture(i)
                start = time.monotonic()
                raster(target, s["triangles"], K, R, t, 64, s["uv"], tex)
                times.append((time.monotonic() - start) * 1000)
        rows.append(
            dict(
                level=level,
                vertices=len(v),
                triangles=len(s["triangles"]),
                geometry_arrays_bytes=sum(a.nbytes for a in s.values()),
                orientation_failures=n,
                area_ratio=[lo, hi],
                edge_stretch_max=edge,
                raster_ms=float(np.mean(times)),
                interpolation_rmse_mm=float(np.mean(capacity)) if capacity else 0,
                case06_pass=False,
                reason="No calibrated benign envelope or full anatomical silhouette; patch stress only.",
            )
        )
    Path(out).write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    import sys

    audit(sys.argv[1])
