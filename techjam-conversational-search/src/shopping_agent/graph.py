from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from shopping_agent.catalog import CatalogIndex
from shopping_agent.question_policy import choose_question, question_options
from shopping_agent.ranking import FallbackReranker
from shopping_agent.retrieval import (
    AttributeIndex,
    LocalDenseIndex,
    SemanticRetriever,
    reciprocal_rank_fusion,
)
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
    semantic_retriever: SemanticRetriever | None = None,
):
    """Build the real-user shopping graph.

    The configured provider is the primary intent interpreter on every turn.
    Deterministic parsing remains a failure fallback. ``semantic_retriever`` is
    the vector-database boundary; the local hashed index is its offline fallback.
    """

    del model
    catalog = CatalogIndex(catalog_path)
    dense_index = semantic_retriever or LocalDenseIndex(catalog)
    attribute_index = AttributeIndex(catalog)
    reranker = FallbackReranker()

    def understand_user(state: ShoppingState) -> dict[str, Any]:
        rule_patch = rule_state_patch(
            state.get("user_message", ""),
            int(state.get("turn", 1)),
        )
        patch, usage = resolve_semantic_patch(
            state.get("user_message", ""),
            int(state.get("turn", 1)),
            rule_patch,
            current_category=state.get("category", ""),
            active_constraints=state.get("active_constraints", []),
            current_semantic_query=state.get("semantic_query", ""),
            intent_summary=state.get("intent_summary", ""),
            user_profile=state.get("user_profile", {}),
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
        newly_specified = {item.field for item in patch.constraints}
        if patch.category:
            newly_specified.add("category")
        no_preference.difference_update(newly_specified)
        resolved_category = patch.category or state.get("category", "")
        if patch.parser == "deepseek" and patch.semantic_query:
            semantic_query = patch.semantic_query
        else:
            fallback_parts = [resolved_category]
            fallback_parts.extend(
                _constraint_text(item)
                for item in active
                if item.operator != "not_contains"
            )
            semantic_query = " ".join(
                dict.fromkeys(part for part in fallback_parts if part)
            ).strip() or patch.semantic_query or state.get("semantic_query", "")
        update: dict[str, Any] = {
            "category": resolved_category,
            "active_constraints": [item.model_dump() for item in active],
            "superseded_constraints": list(state.get("superseded_constraints", []))
            + [item.model_dump() for item in superseded],
            "no_preference": sorted(no_preference),
            "intent_changed": patch.action == "replace",
            "semantic_query": semantic_query,
            "intent_summary": patch.intent_summary or semantic_query or state.get("intent_summary", ""),
            "user_language": patch.language or state.get("user_language", "en"),
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
        parts.extend(
            _constraint_text(item)
            for item in _constraints(state.get("active_constraints", []))
            if item.operator != "not_contains"
        )
        semantic_query = state.get("semantic_query", "").strip()
        if semantic_query:
            parts.append(semantic_query)
        lexical_query = " ".join(dict.fromkeys(part for part in parts if part)).strip()
        return {
            "lexical_query": lexical_query,
            "search_query": semantic_query or lexical_query,
        }

    def lexical_retrieve(state: ShoppingState) -> dict[str, Any]:
        return {
            "lexical_candidates": catalog.search(
                state.get("lexical_query", ""),
                constraints=[],
                limit=300,
            )
        }

    def dense_retrieve(state: ShoppingState) -> dict[str, Any]:
        return {
            "dense_candidates": dense_index.search(
                state.get("semantic_query", "") or state.get("search_query", ""),
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
        broad_query = state.get("category", "") or state.get("lexical_query", "")
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
            query=state.get("semantic_query", "") or state.get("search_query", ""),
            category=state.get("category", ""),
            constraints=_constraints(state.get("active_constraints", [])),
            profile=state.get("user_profile", {}),
            previously_recommended=set(state.get("recommended_asins", [])),
        )
        return {"ranked_candidates": ranked}

    def select_question(state: ShoppingState) -> dict[str, Any]:
        top_ids = [str(item["parent_asin"]) for item in state.get("ranked_candidates", [])[:50]]
        candidate_attributes = attribute_index.candidate_attributes(top_ids)
        known_attributes = {
            item.field
            for item in _constraints(state.get("active_constraints", []))
            if item.operator != "not_contains"
        }
        if state.get("category"):
            known_attributes.add("category")
        attribute, scores = choose_question(
            turn=int(state.get("turn", 1)),
            candidate_attributes=candidate_attributes,
            asked_attributes=list(state.get("asked_attributes", [])),
            no_preference=set(state.get("no_preference", [])),
            known_attributes=known_attributes,
        )
        asked = list(state.get("asked_attributes", []))
        if attribute:
            asked.append(attribute)
        return {
            "ask_attribute": attribute,
            "asked_attributes": asked,
            "question_scores": scores,
            "question_options": question_options(candidate_attributes, attribute),
            "candidate_count": len(state.get("ranked_candidates", [])),
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
        options = [str(item.get("value", "")).replace("_", " ") for item in state.get("question_options", [])]
        language = state.get("user_language", "en")
        if attribute and language == "zh":
            labels = {
                "category": "品类", "material": "材质", "color": "颜色",
                "size": "尺码", "style": "风格", "brand": "品牌",
                "budget": "价格区间", "feature": "功能", "use_case": "使用场景",
            }
            label = labels.get(attribute, attribute)
            if len(options) >= 2:
                message = f"当前结果在{label}上主要有{'、'.join(options)}，你更偏向哪一种？"
            else:
                message = f"为了进一步缩小结果，你对{label}有什么偏好吗？"
        elif attribute:
            label = attribute.replace("_", " ")
            if len(options) >= 2:
                message = f"The current matches mainly differ by {label}: {', '.join(options)}. Which do you prefer?"
            else:
                message = f"To narrow these matches, do you have a preference for {label}?"
        else:
            message = (
                "我已经根据你目前的要求筛选出最接近的结果。"
                if language == "zh"
                else "Here are the closest matches for your current requirements."
            )
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
    builder.add_node("understand_user", understand_user)
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

    builder.add_edge(START, "understand_user")
    builder.add_edge("understand_user", "validate_patch")
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
