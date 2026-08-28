from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shopping_agent.dialogue.question_policy import choose_question, question_options
from shopping_agent.dialogue.response_builder import build_agent_response
from shopping_agent.domain.schemas import Constraint
from shopping_agent.domain.state import ShoppingState
from shopping_agent.ranking.interfaces import CandidateRanker
from shopping_agent.retrieval.attributes import AttributeIndex
from shopping_agent.retrieval.fusion import reciprocal_rank_fusion
from shopping_agent.retrieval.interfaces import SemanticRetriever
from shopping_agent.retrieval.lexical import CatalogIndex
from shopping_agent.understanding.interpreter import (
    StatePatch,
    apply_state_patch,
    resolve_semantic_patch,
    rule_state_patch,
    validate_state_patch,
)


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


@dataclass
class ShoppingGraphNodes:
    """Bound graph-node implementations with explicit component dependencies."""

    catalog: CatalogIndex
    semantic_retriever: SemanticRetriever
    attribute_index: AttributeIndex
    reranker: CandidateRanker

    def understand_user(self, state: ShoppingState) -> dict[str, Any]:
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

    def validate_patch(self, state: ShoppingState) -> dict[str, Any]:
        patch = validate_state_patch(StatePatch.model_validate(state.get("semantic_patch", {})))
        return {
            "semantic_patch": patch.model_dump(mode="json"),
            "semantic_confidence": patch.confidence,
            "semantic_fallback_reasons": patch.fallback_reasons,
        }

    def update_state(self, state: ShoppingState) -> dict[str, Any]:
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
            "intent_summary": patch.intent_summary
            or semantic_query
            or state.get("intent_summary", ""),
            "user_language": patch.language or state.get("user_language", "en"),
            "retrieval_attempt": 0,
            "constraints_relaxed": False,
        }
        if patch.action == "replace":
            update["recommended_asins"] = []
        return update

    def build_query(self, state: ShoppingState) -> dict[str, Any]:
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

    def lexical_retrieve(self, state: ShoppingState) -> dict[str, Any]:
        return {
            "lexical_candidates": self.catalog.search(
                state.get("lexical_query", ""),
                constraints=[],
                limit=300,
            )
        }

    def dense_retrieve(self, state: ShoppingState) -> dict[str, Any]:
        return {
            "dense_candidates": self.semantic_retriever.search(
                state.get("semantic_query", "") or state.get("search_query", ""),
                limit=200,
            )
        }

    def attribute_retrieve(self, state: ShoppingState) -> dict[str, Any]:
        return {
            "attribute_candidates": self.attribute_index.search(
                state.get("category", ""),
                _constraints(state.get("active_constraints", [])),
                limit=200,
            )
        }

    def fuse_candidates(self, state: ShoppingState) -> dict[str, Any]:
        fused = reciprocal_rank_fusion([
            (state.get("lexical_candidates", []), 1.0),
            (state.get("dense_candidates", []), 0.35),
            (state.get("attribute_candidates", []), 0.45),
        ])
        return {"fused_candidates": fused}

    def apply_constraints(self, state: ShoppingState) -> dict[str, Any]:
        constraints = _constraints(state.get("active_constraints", []))
        filtered = [
            candidate
            for candidate in state.get("fused_candidates", [])
            if not self.catalog.violates_hard_constraint(candidate, constraints)
        ]
        return {"filtered_candidates": filtered}

    def relax_and_backfill(self, state: ShoppingState) -> dict[str, Any]:
        constraints = _constraints(state.get("active_constraints", []))
        broad_query = state.get("category", "") or state.get("lexical_query", "")
        fallback = self.catalog.search(broad_query, constraints=constraints, limit=200)
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

    def rerank(self, state: ShoppingState) -> dict[str, Any]:
        ranked = self.reranker.rank(
            state.get("filtered_candidates", []),
            query=state.get("semantic_query", "") or state.get("search_query", ""),
            category=state.get("category", ""),
            constraints=_constraints(state.get("active_constraints", [])),
            profile=state.get("user_profile", {}),
            previously_recommended=set(state.get("recommended_asins", [])),
        )
        return {"ranked_candidates": ranked}

    def select_question(self, state: ShoppingState) -> dict[str, Any]:
        top_ids = [
            str(item["parent_asin"])
            for item in state.get("ranked_candidates", [])[:50]
        ]
        candidate_attributes = self.attribute_index.candidate_attributes(top_ids)
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

    def build_response(self, state: ShoppingState) -> dict[str, Any]:
        return build_agent_response(state)

    def validate_response(self, state: ShoppingState) -> dict[str, Any]:
        errors: list[str] = []
        top_k = min(max(int(state.get("top_k", 10)), 1), 10)
        seen: set[str] = set()
        valid: list[dict[str, Any]] = []
        for item in state.get("recommendations", []):
            parent_asin = str(item.get("parent_asin", ""))
            if parent_asin in seen or parent_asin not in self.catalog.products:
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
