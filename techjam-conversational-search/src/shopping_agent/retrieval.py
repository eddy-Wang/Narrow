from __future__ import annotations

import hashlib
import heapq
import math
import re
from array import array
from collections import Counter, defaultdict
from functools import lru_cache
from typing import Any, Iterable

from shopping_agent.catalog import CatalogIndex, _text, _terms
from shopping_agent.intent import COLORS, MATERIALS
from shopping_agent.schemas import Constraint


CONCEPTS = {
    "cold": "concept_warmth",
    "warm": "concept_warmth",
    "warmth": "concept_warmth",
    "winter": "concept_warmth",
    "thermal": "concept_warmth",
    "insulated": "concept_warmth",
    "run": "concept_running",
    "running": "concept_running",
    "jogging": "concept_running",
    "exercise": "concept_fitness",
    "workout": "concept_fitness",
    "fitness": "concept_fitness",
    "gym": "concept_fitness",
    "waterproof": "concept_water_resistant",
    "water-resistant": "concept_water_resistant",
    "rain": "concept_water_resistant",
    "formal": "concept_dressy",
    "dress": "concept_dressy",
    "dressy": "concept_dressy",
    "casual": "concept_casual",
    "everyday": "concept_casual",
    "comfortable": "concept_comfort",
    "comfort": "concept_comfort",
    "soft": "concept_comfort",
    "durable": "concept_durability",
    "durability": "concept_durability",
    "sturdy": "concept_durability",
    "outdoor": "concept_outdoor",
    "hiking": "concept_outdoor",
    "trail": "concept_outdoor",
}

USE_CASES = {
    "running": {"run", "running", "jogging"},
    "fitness": {"gym", "fitness", "exercise", "workout", "training"},
    "winter": {"winter", "thermal", "warm", "insulated", "snow"},
    "outdoor": {"outdoor", "hiking", "trail", "camping"},
    "work": {"work", "office", "professional", "uniform"},
}

STYLES = {
    "casual": {"casual", "everyday", "relaxed"},
    "formal": {"formal", "dress", "dressy", "business"},
    "sport": {"sport", "athletic", "active", "performance"},
    "vintage": {"vintage", "retro", "classic"},
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
    """A dependency-free hashed semantic vector fallback.

    It is intentionally not a neural embedding model. Stable feature hashing,
    phrase features, and apparel concept normalization provide a dense-retrieval
    shaped interface until a local embedding model is selected.
    """

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
            corpus = " ".join(
                (
                    title,
                    title,
                    _text(product.get("categories")),
                    _text(product.get("features")),
                    _text(product.get("details")),
                    _text(product.get("description")),
                    _text(product.get("store")),
                )
            )
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


class AttributeIndex:
    """Structured apparel attribute index for retrieval and question entropy."""

    def __init__(self, catalog: CatalogIndex) -> None:
        self.catalog = catalog
        self.values: dict[str, dict[str, set[str]]] = {}
        self.postings: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        self.category_term_postings: dict[str, set[str]] = defaultdict(set)
        self._build()

    @staticmethod
    def _price_bucket(price: object) -> str | None:
        try:
            value = float(price)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        if value < 25:
            return "under_25"
        if value < 50:
            return "25_to_50"
        if value < 100:
            return "50_to_100"
        if value < 200:
            return "100_to_200"
        return "over_200"

    def _extract(self, product: dict[str, Any]) -> dict[str, set[str]]:
        corpus = " ".join(
            _text(product.get(field))
            for field in ("title", "categories", "features", "details", "description", "store")
        ).casefold()
        words = set(_terms(corpus))
        attributes: dict[str, set[str]] = {
            "material": {item for item in MATERIALS if item in words},
            "color": {item for item in COLORS if item in words},
            "use_case": {
                name for name, vocabulary in USE_CASES.items() if words & vocabulary
            },
            "style": {
                name for name, vocabulary in STYLES.items() if words & vocabulary
            },
        }
        store = str(product.get("store") or "").strip().casefold()
        if store:
            attributes["brand"] = {store}
        categories = product.get("categories") or []
        if categories:
            attributes["category"] = {str(categories[-1]).strip().casefold()}
        bucket = self._price_bucket(product.get("price"))
        if bucket:
            attributes["budget"] = {bucket}
        return {field: values for field, values in attributes.items() if values}

    def _build(self) -> None:
        for parent_asin, product in self.catalog.products.items():
            attributes = self._extract(product)
            self.values[parent_asin] = attributes
            for field, values in attributes.items():
                for value in values:
                    self.postings[field][value].add(parent_asin)
                    if field == "category":
                        for term in _terms(value):
                            self.category_term_postings[term].add(parent_asin)

    def search(
        self,
        category: str,
        constraints: Iterable[Constraint],
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        scores: defaultdict[str, float] = defaultdict(float)
        category_terms = set(_terms(category))
        if category_terms:
            for term in category_terms:
                for parent_asin in self.category_term_postings.get(term, set()):
                    scores[parent_asin] += 1.0 / len(category_terms)

        for constraint in constraints:
            value = str(constraint.value).casefold()
            if constraint.field in {"material", "color"}:
                for normalized, parent_asins in self.postings[constraint.field].items():
                    if normalized in value or value in normalized:
                        for parent_asin in parent_asins:
                            scores[parent_asin] += 2.0
            elif constraint.field in {"style", "use_case", "brand"}:
                for normalized, parent_asins in self.postings[constraint.field].items():
                    if normalized in value or value in normalized:
                        for parent_asin in parent_asins:
                            scores[parent_asin] += 1.5

        best = heapq.nlargest(
            limit,
            scores.items(),
            key=lambda item: (
                item[1],
                int(self.catalog.products[item[0]].get("rating_number") or 0),
                item[0],
            ),
        )
        products = self.catalog.get_many([parent_asin for parent_asin, _ in best])
        for rank, (product, (_, score)) in enumerate(zip(products, best), start=1):
            product["attribute_rank"] = rank
            product["attribute_score"] = float(score)
        return products

    def candidate_attributes(self, parent_asins: Iterable[str]) -> list[dict[str, set[str]]]:
        return [self.values[parent_asin] for parent_asin in parent_asins if parent_asin in self.values]


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
            fused[parent_asin].update({key: value for key, value in candidate.items() if key not in fused[parent_asin]})
            fused[parent_asin]["rrf_score"] += weight / (rank_constant + rank)
            fused[parent_asin]["route_count"] += 1
    return sorted(
        fused.values(),
        key=lambda item: (-float(item["rrf_score"]), -int(item["route_count"])),
    )[:limit]
