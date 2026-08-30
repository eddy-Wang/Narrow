from __future__ import annotations

import os
from typing import Any

from shopping_agent.ranking.cross_encoder import BgeCrossEncoderReranker, bge_reranker_from_env
from shopping_agent.ranking.fallback import FallbackReranker
from shopping_agent.ranking.interfaces import CandidateRanker
from shopping_agent.ranking.precise import PreciseReranker


def configured_reranker(
    catalog_products: dict[str, dict[str, Any]],
    mode: str | None = None,
) -> CandidateRanker:
    return reranker_from_config(catalog_products, reranker_config_from_env(mode))


def reranker_config_from_env(mode: str | None = None) -> dict[str, Any]:
    """Capture resolved, non-secret settings for evaluation and exact replay."""
    selected = (mode or os.getenv("SHOPPING_AGENT_RERANKER", "precise")).strip().casefold()
    if selected in {"precise", "fallback"}:
        return {"mode": selected}
    if selected in {"bge", "cross_encoder", "bge-reranker-v2-m3"}:
        ranker = bge_reranker_from_env()
        return {
            "mode": "bge",
            "model_name": ranker.model_name,
            "top_n": ranker.top_n,
            "batch_size": ranker.batch_size,
            "max_length": ranker.max_length,
            "device": ranker.device,
        }
    raise ValueError(
        f"Unsupported SHOPPING_AGENT_RERANKER={selected!r}; "
        "expected 'precise', 'fallback', or 'bge'"
    )


def reranker_from_config(
    catalog_products: dict[str, dict[str, Any]], config: dict[str, Any],
) -> CandidateRanker:
    """Restore a recorded run independently of the current shell environment."""
    selected = config["mode"]
    if selected == "precise":
        return PreciseReranker(catalog_products=catalog_products)
    if selected == "fallback":
        return FallbackReranker()
    if selected == "bge":
        return BgeCrossEncoderReranker(**{key: value for key, value in config.items() if key != "mode"})
    raise ValueError(f"Unsupported recorded reranker mode: {selected!r}")
