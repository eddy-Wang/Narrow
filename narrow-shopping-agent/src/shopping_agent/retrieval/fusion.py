from __future__ import annotations

from typing import Any


def reciprocal_rank_fusion(
    routes: list[tuple[list[dict[str, Any]], float]],
    *,
    rank_constant: float = 60.0,
    limit: int = 500,
) -> list[dict[str, Any]]:
    fused: dict[str, dict[str, Any]] = {}
    for candidates, weight in routes:
        for rank, candidate in enumerate(candidates, start=1):
            parent_asin = str(candidate["parent_asin"])
            if parent_asin not in fused:
                fused[parent_asin] = {**candidate, "rrf_score": 0.0, "route_count": 0}
            fused[parent_asin].update({
                key: value for key, value in candidate.items() if key not in fused[parent_asin]
            })
            fused[parent_asin]["rrf_score"] += weight / (rank_constant + rank)
            fused[parent_asin]["route_count"] += 1
    return sorted(
        fused.values(),
        key=lambda item: (-float(item["rrf_score"]), -int(item["route_count"])),
    )[:limit]
