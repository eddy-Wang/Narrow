from __future__ import annotations

from typing import Any

import pytest

from shopping_agent.domain.schemas import Constraint
from shopping_agent.ranking.cross_encoder import (
    BgeCrossEncoderReranker,
    build_product_document,
    build_reranker_query,
)
from shopping_agent.ranking.factory import configured_reranker, reranker_config_from_env, reranker_from_config
from shopping_agent.ranking.precise import PreciseReranker


class FakeCrossEncoder:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.pairs: list[tuple[str, str]] = []
        self.batch_size: int | None = None

    def predict(
        self,
        pairs: list[tuple[str, str]],
        *,
        batch_size: int,
        show_progress_bar: bool,
    ) -> list[float]:
        assert show_progress_bar is False
        self.pairs = pairs
        self.batch_size = batch_size
        return self.scores


def test_cross_encoder_reranks_only_the_configured_head_and_keeps_tail() -> None:
    model = FakeCrossEncoder([0.1, 0.9])
    reranker = BgeCrossEncoderReranker(top_n=2, batch_size=8, model=model)
    candidates = [
        {"parent_asin": "A", "title": "red sandals", "lexical_rank": 1},
        {"parent_asin": "B", "title": "waterproof boots", "lexical_rank": 2},
        {"parent_asin": "C", "title": "blue sneakers", "lexical_rank": 3},
    ]

    ranked = reranker.rank(
        candidates,
        query="waterproof boots",
        category="boots",
        constraints=[Constraint(field="color", value="black")],
        profile={"preference_tags": ["durable"]},
    )

    assert [item["parent_asin"] for item in ranked] == ["B", "A", "C"]
    assert ranked[0]["reranker_score"] == pytest.approx(0.9)
    assert ranked[2]["reranker_explanation"] == ["cross_encoder:outside_top_n"]
    assert len(model.pairs) == 2
    assert model.batch_size == 8
    assert "waterproof boots" in model.pairs[0][0]
    assert "Title: red sandals" in model.pairs[0][1]


def test_query_and_product_documents_keep_structured_shopping_signals() -> None:
    query = build_reranker_query(
        "black running shoes",
        "running shoes",
        [Constraint(field="budget", operator="lte", value=60, strength="hard")],
        {"preference_tags": ["comfortable"]},
    )
    document = build_product_document({
        "title": "Trail Runner",
        "categories": ["Shoes", "Running"],
        "store": "Example",
        "price": 59.99,
        "features": ["Waterproof", "Black"],
    })

    assert "budget at most 60.0 (hard)" in query
    assert "User preferences: comfortable" in query
    assert "Category: Shoes; Running" in document
    assert "Price: 59.99" in document
    assert "Features: Waterproof; Black" in document


def test_factory_defaults_to_precise_and_bge_is_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHOPPING_AGENT_RERANKER", raising=False)
    assert isinstance(configured_reranker({}), PreciseReranker)

    monkeypatch.setenv("SHOPPING_AGENT_RERANKER", "bge")
    bge = configured_reranker({})
    assert isinstance(bge, BgeCrossEncoderReranker)
    assert bge._model is None


def test_factory_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="Unsupported SHOPPING_AGENT_RERANKER"):
        configured_reranker({}, "unknown")


def test_recorded_bge_config_replays_independently_of_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOPPING_AGENT_RERANKER_TOP_N", "75")
    monkeypatch.setenv("SHOPPING_AGENT_RERANKER_DEVICE", "cuda")
    recorded = reranker_config_from_env("bge")
    monkeypatch.setenv("SHOPPING_AGENT_RERANKER_TOP_N", "5")
    monkeypatch.setenv("SHOPPING_AGENT_RERANKER", "precise")
    restored = reranker_from_config({}, recorded)
    assert isinstance(restored, BgeCrossEncoderReranker)
    assert restored.top_n == 75
    assert restored.device == "cuda"
    assert restored._model is None


def test_historical_replay_stays_precise_even_in_bge_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOPPING_AGENT_RERANKER", "bge")
    assert isinstance(reranker_from_config({}, {"mode": "precise"}), PreciseReranker)


def test_explicit_precise_rollback_ignores_bge_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOPPING_AGENT_RERANKER", "bge")
    monkeypatch.setenv("SHOPPING_AGENT_RERANKER_TOP_N", "20")
    ranker = configured_reranker({}, "precise")
    assert isinstance(ranker, PreciseReranker)
    candidates = [{"parent_asin": str(i), "title": "sandals"} for i in range(150)]
    candidates.append({"parent_asin": "target", "title": "waterproof hiking boots"})
    ranked = ranker.rank(candidates, query="waterproof hiking boots", category="", constraints=[])
    assert len(ranked) == 151
    assert ranked[0]["parent_asin"] == "target"


def test_precise_rollback_preserves_repeat_recommendation_penalty() -> None:
    ranker = configured_reranker({}, "precise")
    candidates = [
        {"parent_asin": "seen", "title": "hiking boots"},
        {"parent_asin": "new", "title": "hiking boots"},
    ]
    ranked = ranker.rank(candidates, query="hiking boots", category="", constraints=[], previously_recommended={"seen"})
    assert [item["parent_asin"] for item in ranked] == ["new", "seen"]
