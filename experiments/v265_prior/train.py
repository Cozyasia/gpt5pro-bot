"""Offline training skeleton. Rights admission occurs before loading RGB or models."""

import json
from pathlib import Path
import numpy as np
from .ingest import validate, asset


class PilotDataset:
    def __init__(self, root, split, smoke=False):
        self.root = Path(root).resolve()
        self.admission = validate(root, smoke=smoke)
        self.rows = [
            json.loads(x)
            for x in (self.root / "manifest.jsonl").read_text().splitlines()
            if x.strip()
        ]
        self.rows = [x for x in self.rows if x["split"] == split]
        if not self.rows:
            raise ValueError("empty requested split")
        self.pairs = {}
        for i, r in enumerate(self.rows):
            self.pairs.setdefault(r["identity_id"], []).append(i)
        if any(len(indices) < 2 for indices in self.pairs.values()):
            raise ValueError("paired cross-view samples required")

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        r = self.rows[index]
        candidates = self.pairs[r["identity_id"]]
        pair = candidates[(candidates.index(index) + 1) % len(candidates)]

        def rgb(row):
            # Re-hash at read time to reject post-validation replacement.
            a = np.load(asset(self.root, row["rgb"]), allow_pickle=False)
            return a.transpose(2, 0, 1).astype(np.float32) / 255

        with np.load(asset(self.root, r["neutral_mesh"]), allow_pickle=False) as z:
            neutral = z["vertices"].copy()
        return {
            "rgb": rgb(r),
            "paired_rgb": rgb(self.rows[pair]),
            "neutral": neutral,
            "identity_id": r["identity_id"],
            "record_id": r["record_id"],
        }


def train_step(encoder, decoder, batch, optimizer, supervision, loss_weights):
    """Caller supplies differentiable projection/silhouette supervision adapter.

    It must return output/target dictionaries for every required loss interface.
    No fake masks, bypasses or implicit zero losses. This is not a full trainer.
    """
    import torch
    from .model import supervised_losses

    optimizer.zero_grad(set_to_none=True)
    identity, residual = encoder(batch["rgb"])
    paired, _ = encoder(batch["paired_rgb"])
    neutral = decoder(identity, residual)
    output, target, regions = supervision(batch, neutral, identity, residual)
    output.update(neutral=neutral, coefficients=identity, paired_coefficients=paired)
    loss = supervised_losses(
        output, target, decoder.triangles, regions, decoder.expression_q
    )
    if set(loss) != set(loss_weights):
        raise ValueError("every loss must have an explicit weight")
    total = sum(loss[k] * loss_weights[k] for k in loss)
    if not torch.isfinite(total):
        raise ValueError("nonfinite training loss")
    total.backward()
    if any(
        p.grad is not None and not torch.isfinite(p.grad).all()
        for p in encoder.parameters()
    ):
        raise ValueError("nonfinite gradient")
    torch.nn.utils.clip_grad_norm_(encoder.parameters(), 1.0)
    optimizer.step()
    return {k: float(v.detach()) for k, v in loss.items()}
