import importlib.util
import json
from pathlib import Path

import pytest

from shopping_agent.application.service import ShoppingAgent
from shopping_agent.ranking.precise import PreciseReranker
from shopping_agent.retrieval.lexical import CatalogIndex


@pytest.fixture
def small_catalog(tmp_path):
    products = [
        {"parent_asin": asin, "title": f"{color} running shoes", "categories": ["Shoes"],
         "store": "Example", "features": ["comfortable"], "price": 30}
        for asin, color in (("A", "Black"), ("B", "Blue"))
    ]
    path = tmp_path / "catalog.jsonl"
    path.write_text("".join(json.dumps(p) + "\n" for p in products), encoding="utf-8")
    return path


def test_default_precise_ignores_retired_experiment_environment(small_catalog, monkeypatch):
    monkeypatch.setenv("SHOPPING_AGENT_ENABLE_LLM", "false")
    monkeypatch.setenv("SHOPPING_DENSE_BACKEND", "local")
    monkeypatch.setenv("SHOPPING_AGENT_RERANKER", "bge")
    calls = []
    original_rank = PreciseReranker.rank

    def record_rank(self, candidates, **kwargs):
        calls.append(self.weights["rrf_raw"])
        return original_rank(self, candidates, **kwargs)

    monkeypatch.setattr(PreciseReranker, "rank", record_rank)
    agent = ShoppingAgent(small_catalog)
    agent.reset("default", {})
    result = agent.respond("default", "I need running shoes", 1, 10)
    assert result["recommendations"]
    assert calls == [pytest.approx(256.534140307499)]
    agent.release_session("default")


def test_injected_ranker_remains_connected_after_coarse_migration(small_catalog, monkeypatch):
    monkeypatch.setenv("SHOPPING_AGENT_ENABLE_LLM", "false")
    monkeypatch.setenv("SHOPPING_DENSE_BACKEND", "local")
    class InjectedRanker:
        def rank(self, candidates, **kwargs):
            return sorted([
                {**p, "reranker_score": 9.0 if p["parent_asin"] == "B" else 1.0}
                for p in candidates
            ], key=lambda p: -p["reranker_score"])

    agent = ShoppingAgent(small_catalog, reranker=InjectedRanker())
    agent.reset("migration", {})
    result = agent.respond("migration", "I need running shoes", 1, 10)
    assert result["recommendations"][0]["parent_asin"] == "B"
    trace = agent.get_turn_trace("migration", 1, candidate_limit=10)
    fused = next(row["updates"]["fused_candidates"] for row in trace if "fused_candidates" in row["updates"])
    ranked = next(row["updates"]["ranked_candidates"] for row in trace if "ranked_candidates" in row["updates"])
    assert fused["top"][0]["retrieval_intent"] == "unknown"
    assert ranked["top"][0]["reranker_score"] == 9.0
    agent.release_session("migration")


def test_legacy_diagnostics_keep_old_weights_and_route_limits(small_catalog):
    script = Path(__file__).resolve().parents[3] / "trace-visualizer/scripts/build-diagnostics.py"
    spec = importlib.util.spec_from_file_location("migration_diagnostics", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    catalog = CatalogIndex(small_catalog)
    legacy = module.build_replay_nodes(catalog, {"mode": "precise"}, new_coarse=False)
    current = module.build_replay_nodes(catalog, {"mode": "precise"}, new_coarse=True)
    assert legacy.reranker.weights["rrf_raw"] == pytest.approx(60.50718504951105)
    assert current.reranker.weights["rrf_raw"] == pytest.approx(256.534140307499)

    class RecordingRetriever:
        def __init__(self):
            self.limits = []

        def search(self, query, limit):
            self.limits.append(limit)
            return []

    retriever = RecordingRetriever()
    legacy.semantic_retriever = current.semantic_retriever = retriever
    legacy.dense_retrieve({"semantic_query": "shoes"})
    current.dense_retrieve({"semantic_query": "shoes"})
    assert retriever.limits == [200, 250]
    with pytest.raises(ValueError, match="recorded evidence"):
        module.build_replay_nodes(catalog, {"mode": "precise"}, new_coarse=True, dense_backend="bge")
    with pytest.raises(ValueError, match="recorded evidence"):
        module.build_replay_nodes(catalog, {"mode": "bge"}, new_coarse=False)
