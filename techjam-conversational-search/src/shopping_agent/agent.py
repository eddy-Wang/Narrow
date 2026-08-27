from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel

from shopping_agent.graph import build_shopping_graph
from shopping_agent.schemas import AgentTurn


class ShoppingAgent:
    """Real-user shopping agent with an evaluator-compatible adapter."""

    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        *,
        model: str | BaseChatModel | None = None,
        graph: Any | None = None,
    ) -> None:
        self.graph = graph or build_shopping_graph(model, catalog_path)
        self._profiles: dict[str, dict[str, Any]] = {}
        self._thread_ids: dict[str, str] = {}
        self._turns: dict[str, int] = {}

    def reset(self, session_id: str, user_profile: dict) -> None:
        self._profiles[session_id] = dict(user_profile)
        self._thread_ids[session_id] = f"{session_id}:{uuid.uuid4().hex}"
        self._turns[session_id] = 0

    def start_session(
        self,
        session_id: str | None = None,
        user_profile: dict[str, Any] | None = None,
    ) -> str:
        """Start a normal user session without the competition request shape."""

        session_id = session_id or uuid.uuid4().hex
        self.reset(session_id, user_profile or {})
        return session_id

    def chat(self, session_id: str, user_message: str, *, top_k: int = 10) -> dict[str, Any]:
        """Handle one natural-language message and maintain the turn internally."""

        if session_id not in self._profiles:
            self.reset(session_id, {})
        turn = self._turns.get(session_id, 0) + 1
        return self.respond(session_id, user_message, turn=turn, top_k=top_k)

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict[str, Any]:
        if session_id not in self._profiles:
            raise RuntimeError("reset must be called before respond")
        self._turns[session_id] = max(self._turns.get(session_id, 0), turn)

        payload = {
            "session_id": session_id,
            "turn": turn,
            "top_k": top_k,
            "user_message": user_message,
            "user_profile": self._profiles[session_id],
            "messages": [{"role": "user", "content": json.dumps({
                "turn": turn,
                "top_k": top_k,
                "user_message": user_message,
            }, ensure_ascii=False)}],
        }
        result = self.graph.invoke(
            payload,
            config={"configurable": {"thread_id": self._thread_ids[session_id]}},
        )

        if "response_message" in result:
            return {
                "message": str(result.get("response_message", "")),
                "ask_attribute": result.get("ask_attribute"),
                "recommendations": self._normalize_recommendations(result.get("recommendations", []), top_k),
                "usage": result.get("usage", {"prompt_tokens": 0, "completion_tokens": 0}),
            }

        decision = self._coerce_turn(result)
        return {
            "message": decision.message,
            "ask_attribute": decision.ask_attribute,
            "recommendations": self._normalize_recommendations(
                [item.model_dump(exclude_none=True) for item in decision.recommendations], top_k
            ),
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }

    @staticmethod
    def _normalize_recommendations(items: list[Any], top_k: int) -> list[dict[str, Any]]:
        seen: set[str] = set()
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            parent_asin = str(item.get("parent_asin", "")).strip()
            if not parent_asin or parent_asin in seen:
                continue
            seen.add(parent_asin)
            output: dict[str, Any] = {"parent_asin": parent_asin}
            if isinstance(item.get("score"), (int, float)):
                output["score"] = float(item["score"])
            normalized.append(output)
            if len(normalized) >= min(max(top_k, 1), 10):
                break
        return normalized

    @staticmethod
    def _coerce_turn(result: dict[str, Any]) -> AgentTurn:
        structured = result.get("structured_response")
        if isinstance(structured, AgentTurn):
            return structured
        if isinstance(structured, dict):
            return AgentTurn.model_validate(structured)
        raise ValueError("Graph did not return a valid shopping response")

    def get_intent_state(self, session_id: str) -> dict[str, Any]:
        """Expose maintained intent state for a product UI or debugging panel."""

        if session_id not in self._thread_ids:
            raise KeyError(session_id)
        snapshot = self.graph.get_state(
            {"configurable": {"thread_id": self._thread_ids[session_id]}}
        )
        values = getattr(snapshot, "values", {})
        return {
            "category": values.get("category", ""),
            "active_constraints": values.get("active_constraints", []),
            "superseded_constraints": values.get("superseded_constraints", []),
            "no_preference": values.get("no_preference", []),
            "semantic_query": values.get("semantic_query", ""),
            "intent_summary": values.get("intent_summary", ""),
            "language": values.get("user_language", "en"),
        }

    def get_turn_trace(
        self,
        session_id: str,
        turn: int,
        *,
        candidate_limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return compact node-by-node writes reconstructed from checkpoints."""

        if session_id not in self._thread_ids:
            raise KeyError(session_id)
        config = {"configurable": {"thread_id": self._thread_ids[session_id]}}
        snapshots = [
            snapshot
            for snapshot in self.graph.get_state_history(config)
            if int(snapshot.values.get("turn", 0) or 0) == turn
        ]
        snapshots.sort(key=lambda item: int(item.metadata.get("step", -1)))
        trace: list[dict[str, Any]] = []
        for before, after in zip(snapshots, snapshots[1:]):
            nodes = [str(node) for node in before.next]
            if not nodes or nodes == ["__start__"]:
                continue
            changed = {
                key: value
                for key, value in after.values.items()
                if key not in before.values or before.values[key] != value
            }
            trace.append({
                "step": int(after.metadata.get("step", -1)),
                "nodes": nodes,
                "created_at": after.created_at,
                "updates": self._compact_trace_values(changed, candidate_limit),
            })
        return trace

    def release_session(self, session_id: str) -> None:
        """Release a completed trace session after its artifacts are persisted."""

        thread_id = self._thread_ids.pop(session_id, None)
        self._profiles.pop(session_id, None)
        self._turns.pop(session_id, None)
        checkpointer = getattr(self.graph, "checkpointer", None)
        if thread_id and checkpointer is not None and hasattr(checkpointer, "delete_thread"):
            checkpointer.delete_thread(thread_id)

    @classmethod
    def _compact_trace_values(
        cls,
        values: dict[str, Any],
        candidate_limit: int,
    ) -> dict[str, Any]:
        candidate_keys = {
            "lexical_candidates",
            "dense_candidates",
            "attribute_candidates",
            "fused_candidates",
            "filtered_candidates",
            "ranked_candidates",
        }
        compact: dict[str, Any] = {}
        for key, value in values.items():
            if key in candidate_keys and isinstance(value, list):
                compact[key] = {
                    "count": len(value),
                    "top": [cls._compact_candidate(item) for item in value[:candidate_limit]],
                }
            elif key == "user_profile" and isinstance(value, dict):
                compact[key] = dict(value)
            elif isinstance(value, list) and len(value) > 100:
                compact[key] = {"count": len(value), "head": value[:100]}
            else:
                compact[key] = value
        return compact

    @staticmethod
    def _compact_candidate(item: Any) -> Any:
        if not isinstance(item, dict):
            return item
        retained = (
            "parent_asin", "title", "categories", "store", "price", "features",
            "average_rating", "rating_number", "lexical_rank", "lexical_score",
            "dense_rank", "dense_score", "attribute_rank", "attribute_score",
            "rrf_score", "route_count", "reranker_score", "reranker_explanation",
        )
        return {key: item[key] for key in retained if key in item}


DeepShoppingAgent = ShoppingAgent
