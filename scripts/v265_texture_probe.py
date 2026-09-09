"""Deterministic production-size sampler check, with no research/live models."""

import argparse
import json
from pathlib import Path
import resource
import time
import numpy as np
from neyrobot_prod.v265_canonical_texture import sample_owned_texture


def run(output):
    image = np.zeros((2304, 1856, 3), np.uint8)
    image[:, :, 0] = np.arange(1856, dtype=np.uint16)[None] % 256
    image[:, :, 1] = np.arange(2304, dtype=np.uint16)[:, None] % 256
    image[:, :, 2] = 117
    y, x = np.indices((1145, 1074), dtype=np.float32)
    xy = np.stack((x + 100.5, y + 200.5), axis=2)
    del x, y
    visible = np.ones((1145, 1074), bool)
    owned = np.ones((2304, 1856), bool)
    target = np.ones((1145, 1074), bool)
    target[:, 800:] = False
    target[1000:] = False
    started = time.perf_counter()
    r = sample_owned_texture(image, xy, visible, owned, target)
    np.testing.assert_array_equal(r["texture"][:1000, :800], image[200:1200, 100:900])
    assert not r["texture"][~target].any()
    assert r["available_samples"] == 800000
    root = Path("/sys/fs/cgroup")
    ledger = {
        "elapsed_s": time.perf_counter() - started,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "accepted_pixels": r["available_samples"],
        "protected_pixels": int((~target).sum()),
        "exact_pixel_match": True,
        "cgroup": {
            n: (root / n).read_text().strip()
            for n in ["memory.peak", "memory.max", "memory.swap.max", "memory.events"]
            if (root / n).exists()
        },
        "context": "isolated synthetic sampler, no models or daemon",
        "production_memory_qualified": False,
        "render_prequalified": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(ledger, indent=2))
    print(json.dumps(ledger))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args().output)
