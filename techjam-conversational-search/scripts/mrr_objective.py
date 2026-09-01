"""Single-target LambdaRank with pair weights equal to abs(delta RR@10).

RR itself is discrete. These are pairwise logistic surrogate derivatives,
recomputed at the current ranks, not derivatives of RR. No runtime changes.
"""
from collections import Counter

import numpy as np


def mrr_lambdas(labels, scores, weight, group):
    return _mrr_lambdas(labels, scores, weight, group, top1_bonus=0.0)


def make_mrr_objective(top1_bonus=0.0):
    """Change only loss utility: RR@10 + bonus * I(rank == 1)."""
    if not np.isfinite(top1_bonus) or top1_bonus < 0:
        raise ValueError("top1_bonus must be finite and non-negative")

    def objective(labels, scores, weight, group):
        return _mrr_lambdas(labels, scores, weight, group, top1_bonus)

    return objective


def _mrr_lambdas(labels, scores, weight, group, top1_bonus):
    if sum(group) != len(scores) or len(labels) != len(scores) or not np.isin(labels, [0, 1]).all():
        raise ValueError("Expected binary labels and group sizes covering every row")
    grad = np.zeros_like(scores, dtype=np.float64)
    hess = np.zeros_like(scores, dtype=np.float64)
    start = 0
    for size in group:
        end = start + int(size)
        target = np.flatnonzero(labels[start:end])
        if len(target) != 1:
            raise ValueError("MRR training requires exactly one positive per group")
        positive = int(target[0])
        current = scores[start:end]
        order = np.argsort(-current, kind="stable")
        ranks = np.empty(len(current), dtype=np.int32)
        ranks[order] = np.arange(1, len(current) + 1)
        discounts = np.where(ranks <= 10, 1.0 / ranks, 0.0)
        discounts += top1_bonus * (ranks == 1)
        delta = np.abs(discounts[positive] - discounts)
        probability = 1.0 / (1.0 + np.exp(np.clip(current[positive] - current, -50, 50)))
        pair_grad = delta * probability
        pair_hess = delta * probability * (1.0 - probability)
        # Normalize query lambdas before applying the existing per-session weights.
        total = 2.0 * pair_grad.sum()
        scale = np.log1p(total) / (np.log(2.0) * total) if total > 0 else 1.0
        if weight is not None:
            if not np.allclose(weight[start:end], weight[start]):
                raise ValueError("Each ranking group must have a constant sample weight")
            scale *= weight[start]
        grad[start:end] = pair_grad * scale
        hess[start:end] = pair_hess * scale
        grad[start + positive] = -pair_grad.sum() * scale
        hess[start + positive] = pair_hess.sum() * scale
        start = end
    if start != len(scores):
        raise ValueError("Group sizes must sum to the number of rows")
    return grad, hess


def make_mrr_metric(groups):
    """Session-weighted frozen-turn RR@10, including missing-target groups.

    This is a model-selection proxy, not end-to-end dialogue MRR. Ties follow
    the runtime's lexical-rank tie break. Official test rows must not be passed.
    """
    counts = Counter(g["sample_id"] for g in groups)

    def metric(labels, scores):
        total_rr = total_hit = total_first = 0.0
        start = 0
        for item in groups:
            end = start + len(item["y"])
            order = np.lexsort((item["lexical_ranks"], -scores[start:end]))
            relevant = np.flatnonzero(labels[start:end][order])
            rank = int(relevant[0]) + 1 if len(relevant) else 0
            session_weight = 1.0 / counts[item["sample_id"]]
            if 0 < rank <= 10:
                total_rr += session_weight / rank
                total_hit += session_weight
                total_first += session_weight * (rank == 1)
            start = end
        if start != len(scores):
            raise ValueError("Validation groups do not match the prediction rows")
        return [("mrr_at_10", total_rr / len(counts), True),
                ("hit_at_10", total_hit / len(counts), True),
                ("top1", total_first / len(counts), True)]

    return metric
