from __future__ import annotations

from typing import Any, Protocol


class SemanticRetriever(Protocol):
    """Replaceable vector-search boundary used by the orchestration graph."""

    def search(self, query: str, limit: int = 200) -> list[dict[str, Any]]: ...
