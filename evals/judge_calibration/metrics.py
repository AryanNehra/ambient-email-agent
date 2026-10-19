"""Pure metric functions for judge-calibration analysis: confusion matrix,
Cohen's kappa, false-pass/false-fail rates, and a bootstrap confidence
interval. No I/O, no LLM calls -- unit tested against hand-computed examples.
"""

from __future__ import annotations

import random
from collections import Counter


def confusion_matrix(human: list[str], judge: list[str]) -> dict[tuple[str, str], int]:
    """Count (human_label, judge_label) pairs. Both lists must be same length and order."""
    if len(human) != len(judge):
        raise ValueError("human and judge label lists must be the same length")
    return dict(Counter(zip(human, judge)))


def cohen_kappa(human: list[str], judge: list[str]) -> float:
    """Cohen's kappa for agreement between two raters over the same items."""
    n = len(human)
    if n == 0:
        return float("nan")
    cm = confusion_matrix(human, judge)
    categories = sorted(set(human) | set(judge))

    po = sum(cm.get((c, c), 0) for c in categories) / n

    human_counts = Counter(human)
    judge_counts = Counter(judge)
    pe = sum((human_counts.get(c, 0) / n) * (judge_counts.get(c, 0) / n) for c in categories)

    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def accuracy(human: list[str], judge: list[str]) -> float:
    """Fraction of items where the judge's label matches the human's label."""
    if len(human) != len(judge):
        raise ValueError("human and judge label lists must be the same length")
    if not human:
        return float("nan")
    return sum(1 for h, j in zip(human, judge) if h == j) / len(human)


def false_pass_rate(human: list[str], judge: list[str], pass_label: str = "pass") -> float:
    """Of items the human marked 'fail', the fraction the judge marked 'pass'."""
    pairs = [(h, j) for h, j in zip(human, judge) if h != pass_label]
    if not pairs:
        return float("nan")
    return sum(1 for _, j in pairs if j == pass_label) / len(pairs)


def false_fail_rate(human: list[str], judge: list[str], pass_label: str = "pass") -> float:
    """Of items the human marked 'pass', the fraction the judge marked 'fail'."""
    pairs = [(h, j) for h, j in zip(human, judge) if h == pass_label]
    if not pairs:
        return float("nan")
    return sum(1 for _, j in pairs if j != pass_label) / len(pairs)


def bootstrap_ci(
    values: list[float], *, n_resamples: int = 2000, confidence: float = 0.95, seed: int = 0
) -> tuple[float, float]:
    """A percentile bootstrap CI for the mean of ``values``."""
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(n_resamples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lower_idx = int((1 - confidence) / 2 * n_resamples)
    upper_idx = int((1 + confidence) / 2 * n_resamples) - 1
    return (means[max(lower_idx, 0)], means[min(upper_idx, n_resamples - 1)])
