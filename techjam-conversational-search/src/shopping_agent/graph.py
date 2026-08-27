from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from shopping_agent.catalog import CatalogIndex
from shopping_agent.question_policy import choose_question
from shopping_agent.ranking import FallbackReranker
from shopping_agent.retrieval import AttributeIndex, LocalDenseIndex, reciprocal_rank_fusion
from shopping_agent.schemas import Constraint
from shopping_agent.semantic_state import (
    StatePatch,
    apply_state_patch,
    resolve_semantic_patch,
    rule_state_patch,
    validate_state_patch,
)
from shopping_agent.state import ShoppingState


ALLOWED_ATTRIBUTES = {
    "category", "material", "color", "size", "style", "brand",
    "budget", "feature", "use_case", "other",
}


def _constraint_text(constraint: Constraint) -> str:
    if constraint.field == "budget":
        return f"budget {constraint.value}"
    return str(constraint.value)


def _constraints(values: list[dict[str, Any]]) -> list[Constraint]:
    return [Constraint.model_validate(value) for value in values]


def build_shopping_graph(
    model: str | BaseChatModel | None = None,
    catalog_path: str | Path = "data/catalog.jsonl",
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    managed_persistence: bool = False,
):
    """Build the offline graph with deterministic semantic fallbacks.

    ``model`` remains in the signature for compatibility but is deliberately not
    used. Dense retrieval and reranking have local fallback implementations with
    stable interfaces that can later be replaced by selected local models.
    """

    del model
    catalog = CatalogIndex(catalog_path)
    dense_index = LocalDenseIndex(catalog)
    attribute_index = AttributeIndex(catalog)
    reranker = FallbackReranker()

    def rule_parse(state: ShoppingState) -> dict[str, Any]:
        patch = rule_state_patch(
            state.get("user_message", ""),
            int(state.get("turn", 1)),
        )
        return {
            "semantic_patch": patch.model_dump(mode="json"),
            "semantic_confidence": patch.confidence,
            "semantic_fallback_reasons": patch.fallback_reasons,
            "semantic_usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }

    def route_semantic_parse(state: ShoppingState) -> str:
        patch = StatePatch.model_validate(state.get("semantic_patch", {}))
        return "semantic_fallback" if patch.confidence < 0.7 or patch.fallback_reasons else "validate_patch"

    def semantic_fallback(state: ShoppingState) -> dict[str, Any]:
        patch, usage = resolve_semantic_patch(
            state.get("user_message", ""),
            int(state.get("turn", 1)),
            StatePatch.model_validate(state.get("semantic_patch", {})),
            current_category=state.get("category", ""),
            active_constraints=state.get("active_constraints", []),
        )
        return {
            "semantic_patch": patch.model_dump(mode="json"),
            "semantic_confidence": patch.confidence,
            "semantic_fallback_reasons": patch.fallback_reasons,
            "semantic_usage": usage,
        }

    def validate_patch(state: ShoppingState) -> dict[str, Any]:
        patch = validate_state_patch(StatePatch.model_validate(state.get("semantic_patch", {})))
        return {
            "semantic_patch": patch.model_dump(mode="json"),
            "semantic_confidence": patch.confidence,
            "semantic_fallback_reasons": patch.fallback_reasons,
        }

    def update_state(state: ShoppingState) -> dict[str, Any]:
        patch = StatePatch.model_validate(state.get("semantic_patch", {}))
        active, superseded = apply_state_patch(
            list(state.get("active_constraints", [])),
            patch,
        )
        no_preference = set(state.get("no_preference", []))
        no_preference.update(patch.no_preference)
        update: dict[str, Any] = {
            "category": patch.category or state.get("category", ""),
            "active_constraints": [item.model_dump() for item in active],
            "superseded_constraints": list(state.get("superseded_constraints", []))
            + [item.model_dump() for item in superseded],
            "no_preference": sorted(no_preference),
            "intent_changed": patch.action == "replace",
            "retrieval_attempt": 0,
            "constraints_relaxed": False,
        }
        if patch.action == "replace":
            # Products shown before an override should not receive a novelty
            # penalty under the new active intent.
            update["recommended_asins"] = []
        return update

    def build_query(state: ShoppingState) -> dict[str, Any]:
        parts = [state.get("category", "")]
        parts.extend(_constraint_text(item) for item in _constraints(state.get("active_constraints", [])))
        parts.append(state.get("user_message", ""))
        return {"search_query": " ".join(part for part in parts if part).strip()}

    def lexical_retrieve(state: ShoppingState) -> dict[str, Any]:
        return {
            "lexical_candidates": catalog.search(
                state.get("search_query", ""),
                constraints=[],
                limit=300,
            )
        }

    def dense_retrieve(state: ShoppingState) -> dict[str, Any]:
        return {
            "dense_candidates": dense_index.search(
                state.get("search_query", ""),
                limit=200,
            )
        }

    def attribute_retrieve(state: ShoppingState) -> dict[str, Any]:
        return {
            "attribute_candidates": attribute_index.search(
                state.get("category", ""),
                _constraints(state.get("active_constraints", [])),
                limit=200,
            )
        }

    def fuse_candidates(state: ShoppingState) -> dict[str, Any]:
        fused = reciprocal_rank_fusion([
            (state.get("lexical_candidates", []), 1.0),
            (state.get("dense_candidates", []), 0.35),
            (state.get("attribute_candidates", []), 0.45),
        ])
        return {"fused_candidates": fused}

    def apply_constraints(state: ShoppingState) -> dict[str, Any]:
        constraints = _constraints(state.get("active_constraints", []))
        filtered = [
            candidate
            for candidate in state.get("fused_candidates", [])
            if not catalog.violates_hard_constraint(candidate, constraints)
        ]
        return {"filtered_candidates": filtered}

    def route_after_filter(state: ShoppingState) -> str:
        return "relax_and_backfill" if len(state.get("filtered_candidates", [])) < 30 else "rerank"

    def relax_and_backfill(state: ShoppingState) -> dict[str, Any]:
        constraints = _constraints(state.get("active_constraints", []))
        broad_query = state.get("category", "") or state.get("user_message", "")
        fallback = catalog.search(broad_query, constraints=constraints, limit=200)
        merged = list(state.get("filtered_candidates", []))
        seen = {str(item["parent_asin"]) for item in merged}
        for candidate in fallback:
            parent_asin = str(candidate["parent_asin"])
            if parent_asin not in seen:
                seen.add(parent_asin)
                merged.append({**candidate, "rrf_score": 0.0, "route_count": 1})
        return {
            "filtered_candidates": merged,
            "constraints_relaxed": True,
            "retrieval_attempt": int(state.get("retrieval_attempt", 0)) + 1,
        }

    def rerank(state: ShoppingState) -> dict[str, Any]:
        ranked = reranker.rank(
            state.get("filtered_candidates", []),
            query=state.get("search_query", ""),
            category=state.get("category", ""),
            constraints=_constraints(state.get("active_constraints", [])),
            profile=state.get("user_profile", {}),
            previously_recommended=set(state.get("recommended_asins", [])),
        )
        return {"ranked_candidates": ranked}

    def select_question(state: ShoppingState) -> dict[str, Any]:
        top_ids = [str(item["parent_asin"]) for item in state.get("ranked_candidates", [])[:50]]
        attribute, scores = choose_question(
            turn=int(state.get("turn", 1)),
            candidate_attributes=attribute_index.candidate_attributes(top_ids),
            asked_attributes=list(state.get("asked_attributes", [])),
            no_preference=set(state.get("no_preference", [])),
        )
        asked = list(state.get("asked_attributes", []))
        if attribute:
            asked.append(attribute)
        return {
            "ask_attribute": attribute,
            "asked_attributes": asked,
            "question_scores": scores,
        }

    def build_response(state: ShoppingState) -> dict[str, Any]:
        top_k = min(max(int(state.get("top_k", 10)), 1), 10)
        recommendations = [
            {
                "parent_asin": str(item["parent_asin"]),
                "score": round(float(item["reranker_score"]), 6),
            }
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
            "usage": state.get("semantic_usage", {"prompt_tokens": 0, "completion_tokens": 0}),
        }

    def validate_response(state: ShoppingState) -> dict[str, Any]:
        errors: list[str] = []
        top_k = min(max(int(state.get("top_k", 10)), 1), 10)
        seen: set[str] = set()
        valid: list[dict[str, Any]] = []
        for item in state.get("recommendations", []):
            parent_asin = str(item.get("parent_asin", ""))
            if parent_asin in seen or parent_asin not in catalog.products:
                errors.append(f"invalid_or_duplicate:{parent_asin}")
                continue
            seen.add(parent_asin)
            valid.append(item)
            if len(valid) >= top_k:
                break
        attribute = state.get("ask_attribute")
        if attribute not in ALLOWED_ATTRIBUTES and attribute is not None:
            errors.append(f"invalid_attribute:{attribute}")
            attribute = None
        history = list(state.get("recommended_asins", []))
        history.extend(item["parent_asin"] for item in valid)
        return {
            "ask_attribute": attribute,
            "recommendations": valid,
            "recommended_asins": list(dict.fromkeys(history)),
            "errors": errors,
        }

    builder = StateGraph(ShoppingState)
    builder.add_node("rule_parse", rule_parse)
    builder.add_node("semantic_fallback", semantic_fallback)
    builder.add_node("validate_patch", validate_patch)
    builder.add_node("update_state", update_state)
    builder.add_node("build_query", build_query)
    builder.add_node("lexical_retrieve", lexical_retrieve)
    builder.add_node("dense_retrieve_fallback", dense_retrieve)
    builder.add_node("attribute_retrieve", attribute_retrieve)
    builder.add_node("rrf_fusion", fuse_candidates)
    builder.add_node("constraint_filter", apply_constraints)
    builder.add_node("relax_and_backfill", relax_and_backfill)
    builder.add_node("rerank_fallback", rerank)
    builder.add_node("information_gain_question", select_question)
    builder.add_node("build_response", build_response)
    builder.add_node("validate_response", validate_response)

    builder.add_edge(START, "rule_parse")
    builder.add_conditional_edges(
        "rule_parse",
        route_semantic_parse,
        {
            "semantic_fallback": "semantic_fallback",
            "validate_patch": "validate_patch",
        },
    )
    builder.add_edge("semantic_fallback", "validate_patch")
    builder.add_edge("validate_patch", "update_state")
    builder.add_edge("update_state", "build_query")
    builder.add_edge("build_query", "lexical_retrieve")
    builder.add_edge("build_query", "dense_retrieve_fallback")
    builder.add_edge("build_query", "attribute_retrieve")
    builder.add_edge(
        ["lexical_retrieve", "dense_retrieve_fallback", "attribute_retrieve"],
        "rrf_fusion",
    )
    builder.add_edge("rrf_fusion", "constraint_filter")
    builder.add_conditional_edges(
        "constraint_filter",
        route_after_filter,
        {
            "relax_and_backfill": "relax_and_backfill",
            "rerank": "rerank_fallback",
        },
    )
    builder.add_edge("relax_and_backfill", "rerank_fallback")
    builder.add_edge("rerank_fallback", "information_gain_question")
    builder.add_edge("information_gain_question", "build_response")
    builder.add_edge("build_response", "validate_response")
    builder.add_edge("validate_response", END)

    saver = None if managed_persistence else (checkpointer or InMemorySaver())
    return builder.compile(checkpointer=saver)
