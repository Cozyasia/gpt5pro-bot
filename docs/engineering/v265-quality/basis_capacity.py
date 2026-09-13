"""TRAIN-only geometry PCA oracle, not image reconstruction evidence."""

import argparse, json
from pathlib import Path
import numpy as np

p = argparse.ArgumentParser()
p.add_argument("corpus")
p.add_argument("output")
a = p.parse_args()
root = Path(a.corpus)
rows = [
    json.loads(l)
    for l in (root / "manifest.jsonl").read_text().splitlines()
    if json.loads(l)["view"] == 0
]
train = np.stack(
    [
        np.load(root / r["path"])["neutral"].reshape(-1)
        for r in rows
        if r["split"] == "train"
    ]
)
test = np.stack(
    [
        np.load(root / r["path"])["neutral"].reshape(-1)
        for r in rows
        if r["split"] == "test"
    ]
)
mean = train.mean(0)
u, s, v = np.linalg.svd(train - mean, full_matrices=False)
results = []
for k in [24, 36, 64]:
    b = v[:k]
    pred = mean + ((test - mean) @ b.T) @ b
    results.append(
        dict(
            dimensions=k,
            unseen_oracle_rmse_mm=float(
                np.sqrt(
                    np.mean(
                        np.sum((pred - test).reshape(len(test), -1, 3) ** 2, axis=2)
                    )
                )
                * 1000
            ),
        )
    )
r = dict(
    train_identities=len(train),
    test_identities=len(test),
    effective_rank=int((s > s.max() * 1e-5).sum()),
    results=results,
    interpretation="Oracle geometry projection only. The corpus cannot establish 128/256-dimensional anatomical identity capacity.",
)
Path(a.output).write_text(json.dumps(r, indent=2))
print(json.dumps(r, indent=2))
