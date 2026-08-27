from __future__ import annotations

import json
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import ChatResult

from shopping_agent.agent import DeepShoppingAgent, ShoppingAgent
from shopping_agent.catalog import CatalogIndex
from shopping_agent.graph import build_shopping_graph
from shopping_agent.intent import merge_constraints, parse_message
from shopping_agent.schemas import AgentTurn, Recommendation


def _write_catalog(path: Path) -> None:
    products = [
        {
            "parent_asin": "A",
            "title": "Black leather belt",
            "features": ["100% leather"],
            "details": {"Department": "mens"},
            "description": [],
            "categories": ["Accessories", "Belts"],
            "store": "Example",
            "price": 30.0,
            "average_rating": 4.5,
            "rating_number": 100,
        },
        {
            "parent_asin": "B",
            "title": "Blue running shoe",
            "features": ["breathable mesh"],
            "details": {"Department": "womens"},
            "description": [],
            "categories": ["Shoes", "Running"],
            "store": "Example",
            "price": 80.0,
            "average_rating": 4.4,
            "rating_number": 80,
        },
    ]
    path.write_text("".join(json.dumps(item) + "\n" for item in products), encoding="utf-8")


class FakeGraph:
    def __init__(self) -> None:
        self.configs: list[dict] = []

    def invoke(self, payload: dict, config: dict) -> dict:
        self.configs.append(config)
        return {
            "messages": payload["messages"],
            "structured_response": AgentTurn(
                message="Do you have a material preference?",
                ask_attribute="material",
                recommendations=[
                    Recommendation(parent_asin="A", score=0.9),
                    Recommendation(parent_asin="A", score=0.8),
                    Recommendation(parent_asin="B", score=0.7),
                ],
            ),
        }


class ConstructionOnlyModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "construction-only"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise AssertionError("This model is only used to verify graph construction")

    def bind_tools(self, tools, **kwargs):
        return self


def test_catalog_index_retrieves_matching_product(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.jsonl"
    _write_catalog(catalog_path)
    index = CatalogIndex(catalog_path)

    results = index.search("black leather belt", limit=2)

    assert results[0]["parent_asin"] == "A"


def test_deep_agent_graph_constructs_with_catalog_tools(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.jsonl"
    _write_catalog(catalog_path)

    graph = build_shopping_graph(ConstructionOnlyModel(), catalog_path)

    assert graph is not None


def test_official_adapter_uses_session_as_langgraph_thread_and_deduplicates() -> None:
    graph = FakeGraph()
    agent = DeepShoppingAgent(graph=graph)
    agent.reset("session-1", {"preference_tags": ["comfort"]})

    response = agent.respond("session-1", "I need a belt", turn=1, top_k=10)

    assert response["ask_attribute"] == "material"
    assert [item["parent_asin"] for item in response["recommendations"]] == ["A", "B"]
    assert graph.configs[0]["configurable"]["thread_id"].startswith("session-1:")
    assert response["usage"] == {"prompt_tokens": 0, "completion_tokens": 0}


def test_intent_override_retires_soft_preference_but_keeps_hard_constraint() -> None:
    initial = parse_message("I'm looking for belts. I prefer a casual fit.", turn=1)
    hard = parse_message("For that, what matters is: leather.", turn=2)
    active, _ = merge_constraints([], initial)
    active, _ = merge_constraints(active, hard)

    override = parse_message(
        "Actually, ignore my earlier preference. What I need is: color: black.",
        turn=3,
    )
    active, superseded = merge_constraints(active, override)

    assert any(item.strength == "soft" for item in superseded)
    assert any(str(item.value) == "leather" for item in active)
    assert any("black" in str(item.value) for item in active)


def test_mvp_graph_accumulates_turn_constraints_and_returns_catalog_ids(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.jsonl"
    _write_catalog(catalog_path)
    agent = ShoppingAgent(catalog_path)
    agent.reset("session-mvp", {"preference_tags": ["durability"]})

    first = agent.respond("session-mvp", "I'm looking for accessories, but I'm still exploring.", 1, 10)
    second = agent.respond("session-mvp", "For that, what matters is: leather; color: black.", 2, 10)

    assert first["ask_attribute"] == "other"
    assert second["ask_attribute"] == "other"
    assert second["recommendations"][0]["parent_asin"] == "A"
