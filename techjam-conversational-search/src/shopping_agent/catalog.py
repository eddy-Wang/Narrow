from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from shopping_agent.schemas import Constraint


TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "please", "some",
    "that", "the", "this", "to", "want", "with", "would", "you", "looking",
}


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {item}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def _terms(text: str) -> list[str]:
    return [
        token.lower()
        for token in TOKEN_RE.findall(text)
        if len(token) > 1 and token.lower() not in STOPWORDS
    ]


def _number(value: str | float) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", value.replace(",", ""))
    return float(match.group()) if match else None


class CatalogIndex:
    """Local field-aware lexical index used as an agent tool.

    Positive constraints only exclude a product when the catalog has a reliable,
    structured value that clearly contradicts the request. Missing metadata is
    treated as unknown instead of as a mismatch.
    """

    def __init__(self, catalog_path: str | Path) -> None:
        self.catalog_path = Path(catalog_path)
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.products: dict[str, dict[str, Any]] = {}
        self._build_index()

    def _build_index(self) -> None:
        cursor = self.connection.cursor()
        cursor.execute(
            "CREATE VIRTUAL TABLE products USING fts5("
            "parent_asin UNINDEXED, title, categories, features, details, store, description, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        batch: list[tuple[str, str, str, str, str, str, str]] = []
        with self.catalog_path.open(encoding="utf-8") as handle:
            for line in handle:
                product = json.loads(line)
                parent_asin = str(product["parent_asin"])
                self.products[parent_asin] = product
                batch.append(
                    (
                        parent_asin,
                        _text(product.get("title")),
                        _text(product.get("categories")),
                        _text(product.get("features")),
                        _text(product.get("details")),
                        _text(product.get("store")),
                        _text(product.get("description")),
                    )
                )
                if len(batch) >= 1000:
                    cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
                    batch.clear()
        if batch:
            cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
        self.connection.commit()

    def search(
        self,
        query: str,
        constraints: list[Constraint] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        constraints = constraints or []
        unique_terms = list(dict.fromkeys(_terms(query)))[:40]
        if unique_terms:
            expression = " OR ".join(f'"{term}"' for term in unique_terms)
            rows = self.connection.execute(
                "SELECT parent_asin, bm25(products, 0.0, 8.0, 5.0, 4.0, 2.5, 3.0, 1.0) "
                "FROM products WHERE products MATCH ? ORDER BY 2 LIMIT ?",
                (expression, max(limit * 10, 200)),
            ).fetchall()
            ranked = [(str(row[0]), float(row[1])) for row in rows]
        else:
            ranked = [
                (parent_asin, 0.0)
                for parent_asin in sorted(
                    self.products,
                    key=lambda item: int(self.products[item].get("rating_number") or 0),
                    reverse=True,
                )[: max(limit * 10, 200)]
            ]

        results: list[dict[str, Any]] = []
        for lexical_rank, (parent_asin, lexical_score) in enumerate(ranked, start=1):
            product = self.products[parent_asin]
            if self._violates_hard_constraint(product, constraints):
                continue
            compact = self._compact_product(product, lexical_rank=lexical_rank)
            compact["lexical_score"] = lexical_score
            results.append(compact)
            if len(results) >= limit:
                break
        return results

    def get_many(self, parent_asins: list[str]) -> list[dict[str, Any]]:
        return [
            self._compact_product(self.products[parent_asin])
            for parent_asin in parent_asins
            if parent_asin in self.products
        ]

    def _violates_hard_constraint(
        self,
        product: dict[str, Any],
        constraints: list[Constraint],
    ) -> bool:
        for constraint in constraints:
            if constraint.strength != "hard" or constraint.confidence < 0.75:
                continue
            value = str(constraint.value).lower()
            if constraint.field == "budget":
                price = _number(product.get("price")) if product.get("price") is not None else None
                target = _number(constraint.value)
                if price is None or target is None:
                    continue
                if constraint.operator == "lte" and price > target:
                    return True
                if constraint.operator == "gte" and price < target:
                    return True
                continue

            if constraint.field == "category":
                corpus = f"{_text(product.get('categories'))} {_text(product.get('title'))}".lower()
                if constraint.operator in {"contains", "eq"} and value not in corpus:
                    return True
            elif constraint.field == "brand" and product.get("store"):
                corpus = f"{_text(product.get('store'))} {_text(product.get('title'))}".lower()
                if constraint.operator in {"contains", "eq"} and value not in corpus:
                    return True
            else:
                corpus = " ".join(
                    _text(product.get(field))
                    for field in ("title", "features", "details", "description", "categories", "store")
                ).lower()

            if constraint.operator == "not_contains" and value in corpus:
                return True
        return False

    @staticmethod
    def _compact_product(product: dict[str, Any], lexical_rank: int | None = None) -> dict[str, Any]:
        features = product.get("features") or []
        payload: dict[str, Any] = {
            "parent_asin": str(product["parent_asin"]),
            "title": product.get("title"),
            "categories": product.get("categories") or [],
            "store": product.get("store"),
            "price": product.get("price"),
            "features": features[:4],
            "details": product.get("details") or {},
            "average_rating": product.get("average_rating"),
            "rating_number": product.get("rating_number"),
        }
        if lexical_rank is not None:
            payload["lexical_rank"] = lexical_rank
        return payload
