from inspect import signature
from types import SimpleNamespace

import pytest

from shopping_agent.application.service import ShoppingAgent
from shopping_agent.observability.tracing import CANDIDATE_KEYS, reconstruct_turn_trace


def make_graph():
    candidates = [{"parent_asin": str(i), "title": f"Product {i}"} for i in range(550)]
    values = {"turn": 1, **{key: candidates for key in CANDIDATE_KEYS}}
    before = SimpleNamespace(values={"turn": 1}, metadata={"step": 1}, next=["rerank_fallback"])
    after = SimpleNamespace(values=values, metadata={"step": 2}, created_at="2026-08-30T00:00:00Z")
    return SimpleNamespace(get_state_history=lambda config: [after, before]), candidates


def test_default_trace_records_every_candidate_without_changing_ranking():
    graph, candidates = make_graph()
    trace = reconstruct_turn_trace(graph, "session", 1)
    for key in CANDIDATE_KEYS:
        snapshot = trace[0]["updates"][key]
        assert snapshot["count"] == 550
        assert len(snapshot["top"]) == 550
        assert snapshot["top"][-1]["parent_asin"] == "549"
    assert len(candidates) == 550


def test_trace_limit_remains_configurable():
    graph, _ = make_graph()
    trace = reconstruct_turn_trace(graph, "session", 1, candidate_limit=7)
    assert len(trace[0]["updates"]["ranked_candidates"]["top"]) == 7


def test_service_default_matches_trace_default():
    assert signature(ShoppingAgent.get_turn_trace).parameters["candidate_limit"].default == 0


def test_negative_limit_is_rejected():
    graph, _ = make_graph()
    with pytest.raises(ValueError, match="candidate_limit"):
        reconstruct_turn_trace(graph, "session", 1, candidate_limit=-1)
