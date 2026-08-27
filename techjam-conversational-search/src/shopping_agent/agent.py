from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel

from shopping_agent.graph import build_shopping_graph
from shopping_agent.schemas import AgentTurn


class ShoppingAgent:
    """Official Agent interface backed by the deterministic LangGraph MVP."""

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

    def reset(self, session_id: str, user_profile: dict) -> None:
        self._profiles[session_id] = dict(user_profile)
        self._thread_ids[session_id] = f"{session_id}:{uuid.uuid4().hex}"

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict[str, Any]:
        if session_id not in self._profiles:
            raise RuntimeError("reset must be called before respond")

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


DeepShoppingAgent = ShoppingAgent
