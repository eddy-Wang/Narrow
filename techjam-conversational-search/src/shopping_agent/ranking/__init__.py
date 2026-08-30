"""Candidate ranking components."""

from shopping_agent.ranking.fallback import FallbackReranker
from shopping_agent.ranking.interfaces import CandidateRanker
from shopping_agent.ranking.precise import PreciseReranker
from shopping_agent.ranking.cross_encoder import BgeCrossEncoderReranker
from shopping_agent.ranking.factory import configured_reranker

__all__ = [
    "BgeCrossEncoderReranker",
    "CandidateRanker",
    "FallbackReranker",
    "PreciseReranker",
    "configured_reranker",
]
