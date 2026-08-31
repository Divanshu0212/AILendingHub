"""The WS-0.2.3 reproducibility test.

"CI reproducibility test: retrain a toy model twice from the same triplet ->
assert identical metrics."

A reproducibility test that only asserts "two runs agree" is close to worthless —
a constant function passes it. What makes the test meaningful is the second half:
changing *any* element of the triplet must change the result. Otherwise the
triplet is not actually determining the model, and its three fields are
decoration on a model card.

The learner here is deliberately trivial (logistic regression by gradient descent,
stdlib only). It is not a credit model and must never become one; it exists to
exercise the determinism contract that real training pipelines inherit.

Workstream: WS-0.2.3
"""

from __future__ import annotations

import hashlib
import math
import random
import sys

from .artifact import Triplet, config_hash


def _seed_from(triplet: Triplet) -> int:
    """Derive the RNG seed from the whole triplet.

    Every source of randomness in training must trace to the triplet, or the
    triplet does not determine the model and reproducibility is luck.
    """
    return int(hashlib.sha256(triplet.key().encode("utf-8")).hexdigest()[:8], 16)


def _dataset(snapshot: str, n: int = 400) -> list[tuple[list[float], int]]:
    """Stand-in for reading a tagged lakehouse snapshot (ADR-0001).

    Track B replaces this with an Iceberg read at ``snapshot``. The contract that
    matters is the same in both: the same tag must yield the same rows forever.
    """
    rng = random.Random(int(hashlib.sha256(snapshot.encode()).hexdigest()[:8], 16))
    rows = []
    for _ in range(n):
        x1 = rng.gauss(0, 1)
        x2 = rng.gauss(0, 1)
        logit = 0.9 * x1 - 0.6 * x2
        y = 1 if rng.random() < 1 / (1 + math.exp(-logit)) else 0
        rows.append(([x1, x2], y))
    return rows


def train(triplet: Triplet, config: dict) -> dict:
    """Train the toy model and return its metrics."""
    rng = random.Random(_seed_from(triplet))
    rows = _dataset(triplet.data_snapshot)
    rng.shuffle(rows)

    lr = config.get("learning_rate", 0.05)
    epochs = config.get("epochs", 40)
    weights = [0.0, 0.0]
    bias = 0.0

    for _ in range(epochs):
        for features, label in rows:
            z = sum(w * x for w, x in zip(weights, features)) + bias
            pred = 1 / (1 + math.exp(-max(-60.0, min(60.0, z))))
            error = pred - label
            weights = [w - lr * error * x for w, x in zip(weights, features)]
            bias -= lr * error

    losses = []
    correct = 0
    for features, label in rows:
        z = sum(w * x for w, x in zip(weights, features)) + bias
        pred = 1 / (1 + math.exp(-max(-60.0, min(60.0, z))))
        losses.append(-(label * math.log(max(pred, 1e-12)) + (1 - label) * math.log(max(1 - pred, 1e-12))))
        correct += int((pred >= 0.5) == bool(label))

    return {
        "log_loss": round(sum(losses) / len(losses), 12),
        "accuracy": round(correct / len(rows), 12),
        "weights": [round(w, 12) for w in weights],
        "bias": round(bias, 12),
    }


def run() -> tuple[bool, list[str]]:
    """Run the full reproducibility contract. Returns (passed, findings)."""
    findings: list[str] = []
    config = {"learning_rate": 0.05, "epochs": 40}
    base = Triplet(
        code_commit="c0ffee1234",
        data_snapshot="train-2026-05-retail",
        config_hash=config_hash(config),
    )

    first, second = train(base, config), train(base, config)
    if first != second:
        findings.append(f"same triplet produced different metrics: {first} vs {second}")

    # The half that gives the test its meaning: each triplet element must matter.
    variants = {
        "code_commit": Triplet("different-commit", base.data_snapshot, base.config_hash),
        "data_snapshot": Triplet(base.code_commit, "train-2026-06-retail", base.config_hash),
        "config_hash": Triplet(base.code_commit, base.data_snapshot, config_hash({**config, "epochs": 41})),
    }
    for element, variant in variants.items():
        changed = train(variant, config if element != "config_hash" else {**config, "epochs": 41})
        if changed == first:
            findings.append(
                f"changing {element} left the model identical — the triplet does not "
                "determine the artifact, so recording it proves nothing"
            )

    return not findings, findings


def main() -> int:
    passed, findings = run()
    print("WS-0.2.3 reproducibility test")
    print("  same triplet -> identical metrics ......", "PASS" if passed else "FAIL")
    print("  each triplet element changes the model .", "PASS" if passed else "FAIL")
    for finding in findings:
        print(f"  FAIL {finding}", file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
