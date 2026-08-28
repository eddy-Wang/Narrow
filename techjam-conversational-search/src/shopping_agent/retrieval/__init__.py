"""Replaceable lexical, semantic, attribute, and fusion retrieval components."""

from shopping_agent.retrieval.attributes import AttributeIndex
from shopping_agent.retrieval.fusion import reciprocal_rank_fusion
from shopping_agent.retrieval.interfaces import SemanticRetriever
from shopping_agent.retrieval.lexical import CatalogIndex
from shopping_agent.retrieval.semantic import LocalDenseIndex

__all__ = [
    "AttributeIndex",
    "CatalogIndex",
    "LocalDenseIndex",
    "SemanticRetriever",
    "reciprocal_rank_fusion",
]
