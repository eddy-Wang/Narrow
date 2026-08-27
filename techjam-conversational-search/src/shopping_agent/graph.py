from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from shopping_agent.catalog import CatalogIndex, _text, _terms
from shopping_agent.intent import merge_constraints, parse_message
from shopping_agent.schemas import Constraint
from shopping_agent.state import ShoppingState


def _constraint_text(constraint: Constraint) -> str:
    if constraint.field == "budget":
        return f"budget {constraint.value}"
    return str(constraint.value)


def _product_corpus(product: dict[str, Any]) -> str:
    return " ".join(
        _text(product.get(field))
        for field in ("title", "categories", "features", "details", "store")
    ).casefold()


def _normalized_phrase(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _constraints(values: list[dict[str, Any]]) -> list[Constraint]:
    return [Constraint.model_validate(value) for value in values]


def build_shopping_graph(
    model: str | BaseChatModel | None = None,
    catalog_path: str | Path = "data/catalog.jsonl",
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    managed_persistence: bool = False,
):
    """Build the deterministic, offline LangGraph MVP.

    ``model`` remains in the signature for compatibility. A structured model
    parser can later replace the parse node without changing the graph contract.
    """

    del model
    catalog = CatalogIndex(catalog_path)

    def parse_and_update(state: ShoppingState) -> dict[str, Any]:
        parsed = parse_message(state.get("user_message", ""), int(state.get("turn", 1)))
        active, superseded = merge_constraints(
            _constraints(list(state.get("active_constraints", []))),
            parsed,
        )
        no_preference = set(state.get("no_preference", []))
        no_preference.update(parsed.no_preference)
        return {
            "category": parsed.category or state.get("category", ""),
            "active_constraints": [item.model_dump() for item in active],
            "superseded_constraints": list(state.get("superseded_constraints", []))
            + [item.model_dump() for item in superseded],
            "no_preference": sorted(no_preference),
            "intent_changed": parsed.override,
            "retrieval_attempt": 0,
        }

    def build_query(state: ShoppingState) -> dict[str, Any]:
        parts = [state.get("category", "")]
        parts.extend(_constraint_text(item) for item in _constraints(state.get("active_constraints", [])))
        parts.append(state.get("user_message", ""))
        return {"search_query": " ".join(part for part in parts if part).strip()}

    def retrieve(state: ShoppingState) -> dict[str, Any]:
        attempt = int(state.get("retrieval_attempt", 0))
        constraints = _constraints(state.get("active_constraints", [])) if attempt == 0 else []
        candidates = catalog.search(
            state.get("search_query", ""),
            constraints=constraints,
            limit=300,
        )
        return {"candidates": candidates, "retrieval_attempt": attempt + 1}

    def rerank(state: ShoppingState) -> dict[str, Any]:
        query_terms = set(_terms(state.get("search_query", "")))
        constraints = _constraints(state.get("active_constraints", []))
        category = _normalized_phrase(state.get("category", ""))
        ranked: list[dict[str, Any]] = []

        for candidate in state.get("candidates", []):
            corpus = _product_corpus(candidate)
            normalized_corpus = _normalized_phrase(corpus)
            candidate_terms = set(_terms(corpus))
            term_coverage = len(query_terms & candidate_terms) / max(len(query_terms), 1)
            exact_matches = 0.0
            partial_matches = 0.0
            contradictions = 0.0

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
                else:
                    words = set(_terms(str(constraint.value)))
                    partial_matches += len(words & candidate_terms) / max(len(words), 1)

            category_match = 1.0 if category and category in normalized_corpus else 0.0
            lexical_rank = max(int(candidate.get("lexical_rank") or 300), 1)
            quality = math.log1p(max(int(candidate.get("rating_number") or 0), 0)) / 20.0
            score = (
                8.0 * exact_matches
                + 2.0 * partial_matches
                + 3.0 * category_match
                + 4.0 * term_coverage
                + 2.0 / lexical_rank
                + quality
                - 20.0 * contradictions
            )
            ranked.append({**candidate, "mvp_score": score})

        ranked.sort(key=lambda item: (-float(item["mvp_score"]), int(item.get("lexical_rank") or 999999)))
        return {"ranked_candidates": ranked}

    def select_question(state: ShoppingState) -> dict[str, Any]:
        asked = list(state.get("asked_attributes", []))
        turn = int(state.get("turn", 1))
        message = state.get("user_message", "").casefold()

        # In the published policy `other` reveals up to two still-hidden values.
        # Retrying also handles Boundary sessions, whose first answer is empty.
        if turn <= 3:
            attribute: str | None = "other"
        else:
            cycle = ["feature", "material", "style", "use_case", "budget", "color", "size"]
            unavailable = set(state.get("no_preference", []))
            attribute = next((item for item in cycle if item not in unavailable and item not in asked), None)
        if "no additional preference" in message and turn > 3:
            attribute = None
        if attribute:
            asked.append(attribute)
        return {"ask_attribute": attribute, "asked_attributes": asked}

    def build_response(state: ShoppingState) -> dict[str, Any]:
        top_k = min(max(int(state.get("top_k", 10)), 1), 10)
        recommendations = [
            {"parent_asin": str(item["parent_asin"]), "score": round(float(item["mvp_score"]), 6)}
            for item in state.get("ranked_candidates", [])[:top_k]
        ]
        attribute = state.get("ask_attribute")
        if attribute == "other":
            message = "What other requirements or preferences matter most to you?"
        elif attribute:
            message = f"Do you have a preference for {attribute.replace('_', ' ')}?"
        else:
            message = "Here are the closest matches based on what you have told me."
        return {
            "response_message": message,
            "recommendations": recommendations,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }

    builder = StateGraph(ShoppingState)
    builder.add_node("parse_and_update", parse_and_update)
    builder.add_node("build_query", build_query)
    builder.add_node("retrieve", retrieve)
    builder.add_node("rerank", rerank)
    builder.add_node("select_question", select_question)
    builder.add_node("build_response", build_response)
    builder.add_edge(START, "parse_and_update")
    builder.add_edge("parse_and_update", "build_query")
    builder.add_edge("build_query", "retrieve")
    builder.add_edge("retrieve", "rerank")
    builder.add_edge("rerank", "select_question")
    builder.add_edge("select_question", "build_response")
    builder.add_edge("build_response", END)
    saver = None if managed_persistence else (checkpointer or InMemorySaver())
    return builder.compile(checkpointer=saver)
