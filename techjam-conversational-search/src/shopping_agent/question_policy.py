from __future__ import annotations

import math
from collections import Counter
from typing import Iterable


QUESTION_ATTRIBUTES = ("category", "material", "color", "style", "brand", "budget", "use_case")


def _entropy(values: Iterable[str]) -> float:
    counts = Counter(values)
    total = sum(counts.values())
    if total <= 1 or len(counts) <= 1:
        return 0.0
    raw = -sum((count / total) * math.log2(count / total) for count in counts.values())
    return raw / math.log2(len(counts))


def choose_question(
    *,
    turn: int,
    candidate_attributes: list[dict[str, set[str]]],
    asked_attributes: list[str],
    no_preference: set[str],
) -> tuple[str | None, dict[str, float]]:
    """Choose a protocol-aware early question, then maximize candidate entropy."""

    # `other` is the broad discovery action in the published simulator. Boundary
    # sessions consume the first question, so allow one extra broad request.
    if turn <= 2 or (turn == 3 and "other" in no_preference):
        return "other", {"other": 1.0}

    scores: dict[str, float] = {}
    candidate_count = max(len(candidate_attributes), 1)
    for attribute in QUESTION_ATTRIBUTES:
        if attribute in no_preference or attribute in asked_attributes:
            continue
        observed: list[str] = []
        covered = 0
        for attributes in candidate_attributes:
            values = attributes.get(attribute, set())
            if values:
                covered += 1
                observed.append("|".join(sorted(values)))
        coverage = covered / candidate_count
        scores[attribute] = coverage * _entropy(observed)

    if not scores:
        return None, {}
    attribute, score = max(scores.items(), key=lambda item: item[1])
    if score < 0.05:
        return "feature", scores
    return attribute, scores
