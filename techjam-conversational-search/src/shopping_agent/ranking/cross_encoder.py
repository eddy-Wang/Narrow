from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

from shopping_agent.domain.schemas import Constraint


DEFAULT_MODEL_NAME = "BAAI/bge-reranker-v2-m3"


def _flatten(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [
            f"{key}: {item}"
            for key, item in value.items()
            if item not in (None, "", [])
        ]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)] if value not in (None, "") else []


def _constraint_text(constraint: Constraint) -> str:
    operators = {
        "eq": "equals",
        "contains": "contains",
        "not_contains": "must not contain",
        "lte": "at most",
        "gte": "at least",
    }
    operator = operators.get(constraint.operator, constraint.operator)
    return f"{constraint.field} {operator} {constraint.value} ({constraint.strength})"


def build_reranker_query(
    query: str,
    category: str,
    constraints: list[Constraint],
    profile: dict[str, Any] | None,
) -> str:
    lines = [
        "Rank the product by how well it satisfies the shopping request.",
        f"User request: {query}",
    ]
    if category:
        lines.append(f"Category: {category}")
    if constraints:
        lines.append("Constraints: " + "; ".join(_constraint_text(item) for item in constraints))
    preference_tags = _flatten((profile or {}).get("preference_tags"))
    if preference_tags:
        lines.append("User preferences: " + "; ".join(preference_tags))
    return "\n".join(lines)


def build_product_document(candidate: dict[str, Any]) -> str:
    fields = (
        ("Title", candidate.get("title")),
        ("Category", candidate.get("categories")),
        ("Brand", candidate.get("store")),
        ("Price", candidate.get("price")),
        ("Average rating", candidate.get("average_rating")),
        ("Rating count", candidate.get("rating_number")),
        ("Features", candidate.get("features")),
        ("Details", candidate.get("details")),
        ("Description", candidate.get("description")),
    )
    lines: list[str] = []
    for label, value in fields:
        values = _flatten(value)
        if values:
            lines.append(f"{label}: {'; '.join(values)}")
    return "\n".join(lines)


def _float_scores(values: Any) -> list[float]:
    if hasattr(values, "tolist"):
        values = values.tolist()
    if isinstance(values, (int, float)):
        return [float(values)]
    if not isinstance(values, Iterable):
        raise TypeError("Cross-encoder predict() must return an iterable of scores")
    scores: list[float] = []
    for value in values:
        if isinstance(value, (list, tuple)):
            if len(value) != 1:
                raise ValueError("Expected one relevance score per query-product pair")
            value = value[0]
        scores.append(float(value))
    return scores


class BgeCrossEncoderReranker:
    """Lazy-loaded BGE cross-encoder behind the existing CandidateRanker API.

    Only the first ``top_n`` candidates are sent through the expensive model.
    Candidates outside that window are retained, in their original order, below
    the cross-encoded candidates so switching rankers never changes retrieval or
    hard-constraint filtering.
    """

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_MODEL_NAME,
        top_n: int = 100,
        batch_size: int = 16,
        max_length: int = 512,
        device: str | None = None,
        model: Any | None = None,
    ) -> None:
        if top_n < 1:
            raise ValueError("top_n must be at least 1")
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self.model_name = model_name
        self.top_n = top_n
        self.batch_size = batch_size
        self.max_length = max_length
        self.device = device
        self._model = model

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError(
                "BGE reranking requires the optional 'rerank' dependencies. "
                "Install them with: uv sync --extra rerank"
            ) from exc
        self._model = CrossEncoder(
            self.model_name,
            max_length=self.max_length,
            device=self.device,
        )
        return self._model

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
        del previously_recommended
        if not candidates:
            return []

        head = candidates[: self.top_n]
        reranker_query = build_reranker_query(query, category, constraints, profile)
        pairs = [(reranker_query, build_product_document(candidate)) for candidate in head]
        scores = _float_scores(
            self._load_model().predict(
                pairs,
                batch_size=self.batch_size,
                show_progress_bar=False,
            )
        )
        if len(scores) != len(head):
            raise ValueError(
                f"Cross-encoder returned {len(scores)} scores for {len(head)} candidates"
            )

        ranked_head = [
            {
                **candidate,
                "reranker_score": score,
                "reranker_explanation": [f"cross_encoder:{self.model_name}"],
            }
            for candidate, score in zip(head, scores)
        ]
        ranked_head.sort(
            key=lambda item: (
                -float(item["reranker_score"]),
                int(item.get("lexical_rank") or 999999),
            )
        )

        tail_floor = min(scores) - 1.0
        ranked_tail = [
            {
                **candidate,
                "reranker_score": tail_floor - offset * 1e-6,
                "reranker_explanation": ["cross_encoder:outside_top_n"],
            }
            for offset, candidate in enumerate(candidates[self.top_n :], start=1)
        ]
        return ranked_head + ranked_tail


def bge_reranker_from_env() -> BgeCrossEncoderReranker:
    return BgeCrossEncoderReranker(
        model_name=os.getenv("SHOPPING_AGENT_RERANKER_MODEL", DEFAULT_MODEL_NAME).strip()
        or DEFAULT_MODEL_NAME,
        top_n=int(os.getenv("SHOPPING_AGENT_RERANKER_TOP_N", "100")),
        batch_size=int(os.getenv("SHOPPING_AGENT_RERANKER_BATCH_SIZE", "16")),
        max_length=int(os.getenv("SHOPPING_AGENT_RERANKER_MAX_LENGTH", "512")),
        device=os.getenv("SHOPPING_AGENT_RERANKER_DEVICE", "").strip() or None,
    )
