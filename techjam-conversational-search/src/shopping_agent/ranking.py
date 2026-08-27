from __future__ import annotations

import math
import re
from typing import Any

from shopping_agent.catalog import _text, _terms
from shopping_agent.schemas import Constraint


def _normalized_phrase(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _product_corpus(product: dict[str, Any]) -> str:
    return " ".join(
        _text(product.get(field))
        for field in ("title", "categories", "features", "details", "store")
    ).casefold()


class FallbackReranker:
    """Cross-encoder-shaped deterministic fallback with explainable features."""

    def rank(
        self,
        candidates: list[dict[str, Any]],
        *,
        query: str,
        category: str,
        constraints: list[Constraint],
        profile: dict[str, Any] | None = None,
        previously_recommended: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        query_terms = set(_terms(query))
        category_phrase = _normalized_phrase(category)
        profile_terms = set(_terms(" ".join(str(item) for item in (profile or {}).get("preference_tags", []))))
        previously_recommended = previously_recommended or set()
        ranked: list[dict[str, Any]] = []

        for candidate in candidates:
            corpus = _product_corpus(candidate)
            normalized_corpus = _normalized_phrase(corpus)
            candidate_terms = set(_terms(corpus))
            term_coverage = len(query_terms & candidate_terms) / max(len(query_terms), 1)
            exact_matches = 0.0
            partial_matches = 0.0
            contradictions = 0.0
            explanations: list[str] = []

            for constraint in constraints:
                if constraint.field == "budget":
                    price = candidate.get("price")
                    if price is not None and constraint.operator == "lte":
                        if float(price) <= float(constraint.value):
                            exact_matches += 1.0
                        else:
                            contradictions += 1.0
                    continue
                phrase = _normalized_phrase(str(constraint.value))
                if phrase and phrase in normalized_corpus:
                    exact_matches += 1.0
                    explanations.append(f"exact:{constraint.field}")
                else:
                    words = set(_terms(str(constraint.value)))
                    partial_matches += len(words & candidate_terms) / max(len(words), 1)

            category_match = 1.0 if category_phrase and category_phrase in normalized_corpus else 0.0
            profile_match = len(profile_terms & candidate_terms) / max(len(profile_terms), 1)
            lexical_rank = max(int(candidate.get("lexical_rank") or 300), 1)
            quality = math.log1p(max(int(candidate.get("rating_number") or 0), 0)) / 20.0
            novelty_penalty = 1.0 if str(candidate["parent_asin"]) in previously_recommended else 0.0
            score = (
                8.0 * exact_matches
                + 2.0 * partial_matches
                + 3.0 * category_match
                + 4.0 * term_coverage
                + 2.0 / lexical_rank
                + 10.0 * float(candidate.get("rrf_score") or 0.0)
                + 0.75 * float(candidate.get("dense_score") or 0.0)
                + 0.5 * float(candidate.get("attribute_score") or 0.0)
                + 0.25 * profile_match
                + quality
                - 20.0 * contradictions
                - 1.25 * novelty_penalty
            )
            ranked.append({
                **candidate,
                "reranker_score": score,
                "reranker_explanation": explanations,
            })

        ranked.sort(
            key=lambda item: (
                -float(item["reranker_score"]),
                int(item.get("lexical_rank") or 999999),
            )
        )
        return ranked
