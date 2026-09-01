from __future__ import annotations

from typing import Any, Protocol

from shopping_agent.domain.schemas import Constraint


class CandidateRanker(Protocol):
    def rank(
        self,
        candidates: list[dict[str, Any]],
        *,
        query: str,
        category: str,
        constraints: list[Constraint],
        profile: dict[str, Any] | None = None,
        previously_recommended: set[str] | None = None,
    ) -> list[dict[str, Any]]: ...
