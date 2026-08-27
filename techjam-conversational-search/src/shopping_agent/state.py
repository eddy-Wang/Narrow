from __future__ import annotations

from typing import Any, TypedDict

class ShoppingState(TypedDict, total=False):
    session_id: str
    turn: int
    top_k: int
    user_message: str
    user_profile: dict[str, Any]
    category: str
    # Constraints are checkpointed as plain dictionaries. This keeps LangGraph
    # serialization portable and avoids allowing arbitrary application classes.
    active_constraints: list[dict[str, Any]]
    superseded_constraints: list[dict[str, Any]]
    no_preference: list[str]
    asked_attributes: list[str]
    intent_changed: bool
    search_query: str
    candidates: list[dict[str, Any]]
    ranked_candidates: list[dict[str, Any]]
    retrieval_attempt: int
    ask_attribute: str | None
    response_message: str
    recommendations: list[dict[str, Any]]
    usage: dict[str, int]
    errors: list[str]
