from __future__ import annotations

from typing import Any

from shopping_agent.domain.schemas import Constraint
from shopping_agent.ranking.precise_features import build_global_idf, extract_batch_features

# Fitted by scripts/fit_precise_reranker_weights.py with class-balanced
# logistic regression over the runtime's 13 features. Training replayed 2,000
# synthetic sessions through the same intent-dependent coarse pipeline used at
# inference; public evaluation samples were not used for fitting. Caveats:
# C=100 was not re-swept for this pipeline, targets came from a 600-product
# qualifying pool, and the fit uses one seeded synthetic draw.
DEFAULT_WEIGHTS: dict[str, float] = {
    "exact_matches": -0.32621388885938607,
    "partial_matches": -10.450430809807001,
    "category_match": 1.71833145762721,
    "term_coverage": 2.039800023104378,
    "lexical_signal": 1.7999938906521709,
    "rrf_raw": 256.534140307499,
    "dense_raw": -5.069134926064081,
    "attribute_raw": 0.14235436628358844,
    "profile_match": 0.3678694187211294,
    "quality": 23.341790703935995,
    "contradictions": -3.4994937475756673,
    "budget_penalty": 0.0,
    "novelty_penalty": -2.3446468806044254,
}


class PreciseReranker:
    """Feature-scored precise ranker.

    Same CandidateRanker contract as FallbackReranker. Adds: bayesian-shrunk
    quality (average_rating x rating_number instead of rating_number alone),
    explicit soft-constraint contradiction detection (material/color/style/
    use_case/brand, not just budget), and a continuous budget penalty instead
    of a flat one. Recall-signal handling (rrf/dense/attribute/lexical) and
    term coverage intentionally mirror FallbackReranker's scale so the two
    implementations remain score-compatible.

    Pass `catalog_products` (a CatalogIndex.products-shaped dict) once at
    construction to enable proper corpus-wide idf weighting for term_coverage
    / profile_match; without it, term coverage falls back to a plain overlap
    ratio (same as FallbackReranker), which is still correct, just less
    precise about which terms are actually rare.
    """

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        catalog_products: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.weights = {**DEFAULT_WEIGHTS, **(weights or {})}
        self.idf = build_global_idf(catalog_products) if catalog_products else None

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
        if not candidates:
            return []

        features = extract_batch_features(
            candidates,
            query=query,
            category=category,
            constraints=constraints,
            profile=profile,
            previously_recommended=previously_recommended,
            idf=self.idf,
        )

        w = self.weights
        ranked: list[dict[str, Any]] = []
        for candidate, feat in zip(candidates, features):
            score = (
                w["exact_matches"] * feat.exact_matches
                + w["partial_matches"] * feat.partial_matches
                + w["category_match"] * feat.category_match
                + w["term_coverage"] * feat.term_coverage
                + w["lexical_signal"] * feat.lexical_signal
                + w["rrf_raw"] * feat.rrf_raw
                + w["dense_raw"] * feat.dense_raw
                + w["attribute_raw"] * feat.attribute_raw
                + w["profile_match"] * feat.profile_match
                + w["quality"] * feat.quality
                + w["contradictions"] * feat.contradictions
                + w["budget_penalty"] * feat.budget_penalty
                + w["novelty_penalty"] * feat.novelty_penalty
            )
            ranked.append({
                **candidate,
                "reranker_score": score,
                "reranker_explanation": feat.explanations,
            })

        ranked.sort(
            key=lambda item: (
                -float(item["reranker_score"]),
                int(item.get("lexical_rank") or 999999),
            )
        )
        return ranked
