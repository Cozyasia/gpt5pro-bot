"""Independent seed calibration and pose stress for the ORIGINAL PATCH only."""

import argparse, json
from pathlib import Path
import numpy as np
from scipy.ndimage import binary_fill_holes
from experiments.v265_quality.factory import surface, anatomy, expression, camera
from experiments.v265_prior.evaluate import topology_metrics
from experiments.v265_selfhost.geometry import raster

p = argparse.ArgumentParser()
p.add_argument("output")
a = p.parse_args()
results = []
for level in (0, 1):
    s = surface(level)
    rng = np.random.default_rng(7730)
    areas = []
    edges = []
    calibration_failures = 0
    for _ in range(256):
        v = anatomy(s, rng.uniform(-1, 1, 24), rng.uniform(-1, 1, 12))
        v = expression(s, v, rng.uniform(-1, 1, 8))
        m = topology_metrics(v, s["neutral"], s["triangles"])
        areas.extend([m["local_area_ratio"]["min"], m["local_area_ratio"]["max"]])
        edges.extend([m["edge_stretch"]["min"], m["edge_stretch"]["max"]])
        calibration_failures += m["orientation_failures"]
    envelope = dict(area=[min(areas), max(areas)], edge=[min(edges), max(edges)])
    rng = np.random.default_rng(990)
    failures = 0
    holes = 0
    outside = 0
    rows = []
    for i in range(32):
        v = anatomy(s, rng.uniform(-1, 1, 24), rng.uniform(-1, 1, 12))
        v = expression(s, v, rng.uniform(-1, 1, 8))
        m = topology_metrics(v, s["neutral"], s["triangles"])
        failures += m["orientation_failures"]
        valid = (
            m["local_area_ratio"]["min"] >= envelope["area"][0]
            and m["local_area_ratio"]["max"] <= envelope["area"][1]
            and m["edge_stretch"]["min"] >= envelope["edge"][0]
            and m["edge_stretch"]["max"] <= envelope["edge"][1]
        )
        outside += int(not valid)
        K, R, t = camera((-1) ** i * (40 + i % 26), (-1) ** (i // 2) * 25)
        mask = raster(v, s["triangles"], K, R, t, 64)["visibility"]
        hole = int((binary_fill_holes(mask) & ~mask).sum())
        holes += hole
        rows.append(dict(case=i, outside_envelope=not valid, hole_pixels=hole))
    results.append(
        dict(
            level=level,
            calibration_samples=256,
            stress_samples=32,
            calibration_orientation_failures=calibration_failures,
            benign_observed_envelope=envelope,
            stress_orientation_failures=failures,
            stress_hole_pixels=holes,
            stress_outside_envelope=outside,
            patch_numerical_pass=calibration_failures == 0
            and failures == 0
            and holes == 0
            and outside == 0,
            full_anatomical_surface_qualified=False,
            rows=rows,
        )
    )
Path(a.output).write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
