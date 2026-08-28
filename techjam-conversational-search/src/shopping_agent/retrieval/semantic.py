from __future__ import annotations

import hashlib
import heapq
import math
from array import array
from collections import Counter, defaultdict
from functools import lru_cache
from typing import Any

from shopping_agent.domain.product_text import _text, _terms
from shopping_agent.retrieval.lexical import CatalogIndex


CONCEPTS = {
    "cold": "concept_warmth", "warm": "concept_warmth",
    "warmth": "concept_warmth", "winter": "concept_warmth",
    "thermal": "concept_warmth", "insulated": "concept_warmth",
    "run": "concept_running", "running": "concept_running",
    "jogging": "concept_running", "exercise": "concept_fitness",
    "workout": "concept_fitness", "fitness": "concept_fitness",
    "gym": "concept_fitness", "waterproof": "concept_water_resistant",
    "water-resistant": "concept_water_resistant", "rain": "concept_water_resistant",
    "formal": "concept_dressy", "dress": "concept_dressy",
    "dressy": "concept_dressy", "casual": "concept_casual",
    "everyday": "concept_casual", "comfortable": "concept_comfort",
    "comfort": "concept_comfort", "soft": "concept_comfort",
    "durable": "concept_durability", "durability": "concept_durability",
    "sturdy": "concept_durability", "outdoor": "concept_outdoor",
    "hiking": "concept_outdoor", "trail": "concept_outdoor",
}


def _semantic_terms(text: str) -> list[str]:
    base = _terms(text)
    expanded: list[str] = []
    for token in base:
        stem = token
        if len(token) > 5 and token.endswith("ing"):
            stem = token[:-3]
        elif len(token) > 4 and token.endswith("s"):
            stem = token[:-1]
        expanded.extend((token, f"stem_{stem}"))
        concept = CONCEPTS.get(token)
        if concept:
            expanded.append(concept)
    expanded.extend(f"bigram_{left}_{right}" for left, right in zip(base, base[1:]))
    return expanded


@lru_cache(maxsize=100_000)
def _hashed_feature(token: str, dimensions: int) -> tuple[int, int]:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest[:4], "little") % dimensions, (1 if digest[4] & 1 else -1)


class LocalDenseIndex:
    """Dependency-free hashed semantic-vector fallback."""

    def __init__(self, catalog: CatalogIndex, dimensions: int = 512) -> None:
        self.catalog = catalog
        self.dimensions = dimensions
        self.asins: list[str] = []
        self.posting_ids = [array("I") for _ in range(dimensions)]
        self.posting_values = [array("f") for _ in range(dimensions)]
        self._build()

    def _hash_vector(self, text: str) -> dict[int, float]:
        counts: Counter[int] = Counter()
        for token in _semantic_terms(text):
            bucket, sign = _hashed_feature(token, self.dimensions)
            counts[bucket] += sign
        norm = math.sqrt(sum(value * value for value in counts.values())) or 1.0
        return {bucket: value / norm for bucket, value in counts.items() if value}

    def _build(self) -> None:
        for doc_id, (parent_asin, product) in enumerate(self.catalog.products.items()):
            self.asins.append(parent_asin)
            title = _text(product.get("title"))
            corpus = " ".join((
                title,
                title,
                _text(product.get("categories")),
                _text(product.get("features")),
                _text(product.get("details")),
                _text(product.get("description")),
                _text(product.get("store")),
            ))
            for bucket, value in self._hash_vector(corpus).items():
                self.posting_ids[bucket].append(doc_id)
                self.posting_values[bucket].append(value)

    def search(self, query: str, limit: int = 200) -> list[dict[str, Any]]:
        scores: defaultdict[int, float] = defaultdict(float)
        for bucket, query_value in self._hash_vector(query).items():
            for doc_id, doc_value in zip(self.posting_ids[bucket], self.posting_values[bucket]):
                scores[doc_id] += query_value * doc_value
        best = heapq.nlargest(limit, scores.items(), key=lambda item: item[1])
        products = self.catalog.get_many([self.asins[doc_id] for doc_id, _ in best])
        for rank, (product, (_, score)) in enumerate(zip(products, best), start=1):
            product["dense_rank"] = rank
            product["dense_score"] = float(score)
        return products
