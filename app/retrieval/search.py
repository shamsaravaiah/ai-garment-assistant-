from __future__ import annotations

import re
from typing import Any

import httpx

from app.config import Settings
from app.models.schemas import IntentFilters, ProductCard
from app.retrieval.images import looks_like_gift_card, pick_product_image


_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_\-\s]+$")

# Expand casual intents to indexed occasion tags.
_OCCASION_EXPAND = {
    "date": ["date", "evening"],
    "date night": ["date", "evening"],
    "datenight": ["date", "evening"],
    "night out": ["evening", "party", "date"],
    "party": ["party", "evening"],
    "work": ["work", "office"],
    "office": ["work", "office"],
}

_NON_APPAREL = {"accessory", "bag", "shoes", "shoe", "socks", "hat", "belt", "gift"}


def _escape_odata_string(value: str) -> str:
    return value.replace("'", "''")


def _safe_filter_value(value: str) -> str | None:
    cleaned = value.strip()
    if not cleaned or not _SAFE_TOKEN.match(cleaned):
        return None
    return cleaned


def _collection_any(field: str, values: list[str]) -> str | None:
    parts: list[str] = []
    seen: set[str] = set()
    for raw in values:
        token = _safe_filter_value(raw.lower())
        if not token or token in seen:
            continue
        seen.add(token)
        parts.append(f"{field}/any(t: t eq '{_escape_odata_string(token)}')")
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return "(" + " or ".join(parts) + ")"


def _expanded_occasions(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        key = raw.strip().lower()
        expanded = _OCCASION_EXPAND.get(key, [key])
        for item in expanded:
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


class SearchClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _url(self) -> str:
        endpoint = self.settings.azure_search_endpoint.rstrip("/")
        index = self.settings.azure_search_index_name
        return f"{endpoint}/indexes/{index}/docs/search?api-version=2024-07-01"

    def build_filter(
        self,
        filters: IntentFilters,
        *,
        include_tags: bool = True,
        exclude_non_apparel: bool = True,
    ) -> str | None:
        clauses: list[str] = []
        if filters.price_max is not None:
            clauses.append(f"price le {float(filters.price_max)}")
        if filters.price_min is not None:
            clauses.append(f"price ge {float(filters.price_min)}")
        if filters.currency:
            currency = _safe_filter_value(filters.currency.upper())
            if currency:
                clauses.append(f"currency eq '{_escape_odata_string(currency)}'")
        if filters.gender:
            gender = _safe_filter_value(filters.gender.lower())
            if gender:
                clauses.append(f"gender eq '{_escape_odata_string(gender)}'")
        if filters.garment_type:
            garment = _safe_filter_value(filters.garment_type.lower())
            if garment:
                clauses.append(f"garment_type eq '{_escape_odata_string(garment)}'")
        elif exclude_non_apparel:
            # Keep null garment_type docs; drop obvious non-apparel noise.
            banned = " and ".join(
                f"garment_type ne '{_escape_odata_string(g)}'" for g in sorted(_NON_APPAREL)
            )
            if banned:
                clauses.append(f"(garment_type eq null or ({banned}))")

        if include_tags:
            occasion_clause = _collection_any(
                "occasion", _expanded_occasions(filters.occasion)
            )
            if occasion_clause:
                clauses.append(occasion_clause)
            style_clause = _collection_any("style", filters.style[:3])
            if style_clause:
                clauses.append(style_clause)
            colors_clause = _collection_any("colors", filters.colors[:3])
            if colors_clause:
                clauses.append(colors_clause)

        return " and ".join(clauses) if clauses else None

    def search(
        self,
        vector: list[float],
        filters: IntentFilters,
        top_k: int,
        text_query: str | None = None,
    ) -> list[ProductCard]:
        # Keyword query must not include prices (gift cards match "500 SEK").
        keyword = (text_query or filters.retrieval_query or "").strip()
        keyword = re.sub(r"\b\d+([.,]\d+)?\s*(sek|kr|kronor)?\b", "", keyword, flags=re.I)
        keyword = re.sub(r"\s+", " ", keyword).strip() or None

        # Over-fetch so we can drop gift cards / bad images and still fill top_k.
        fetch_k = min(max(top_k * 4, 12), 40)

        attempts = [
            {"include_tags": True, "exclude_non_apparel": True},
            {"include_tags": True, "exclude_non_apparel": False},
            {"include_tags": False, "exclude_non_apparel": True},
            {"include_tags": False, "exclude_non_apparel": False},
        ]

        for attempt in attempts:
            cards = self._execute_search(
                vector=vector,
                filters=filters,
                fetch_k=fetch_k,
                keyword=keyword,
                **attempt,
            )
            cleaned = self._post_filter(cards)
            if cleaned:
                return cleaned[:top_k]
        return []

    def _execute_search(
        self,
        *,
        vector: list[float],
        filters: IntentFilters,
        fetch_k: int,
        keyword: str | None,
        include_tags: bool,
        exclude_non_apparel: bool,
    ) -> list[ProductCard]:
        payload: dict[str, Any] = {
            "count": True,
            "top": fetch_k,
            "select": (
                "product_id,name,brand,price,currency,description,"
                "source_url,blob_url,category_path,gender,garment_type,"
                "occasion,style,colors"
            ),
            "vectorQueries": [
                {
                    "kind": "vector",
                    "vector": vector,
                    "fields": "content_vector",
                    "k": fetch_k,
                }
            ],
        }
        odata_filter = self.build_filter(
            filters,
            include_tags=include_tags,
            exclude_non_apparel=exclude_non_apparel,
        )
        if odata_filter:
            payload["filter"] = odata_filter
        if keyword:
            payload["search"] = keyword

        headers = {
            "Content-Type": "application/json",
            "api-key": self.settings.search_api_key,
        }
        with httpx.Client(timeout=30.0) as client:
            response = client.post(self._url(), headers=headers, json=payload)
            if response.status_code >= 400:
                # Soft-fail on bad filter combos; caller tries a looser attempt.
                return []
            data = response.json()

        cards: list[ProductCard] = []
        for doc in data.get("value", []):
            product_id = str(doc.get("product_id") or doc.get("id") or "")
            if not product_id:
                continue
            cards.append(
                ProductCard(
                    product_id=product_id,
                    name=doc.get("name"),
                    brand=doc.get("brand"),
                    price=doc.get("price"),
                    currency=doc.get("currency"),
                    description=doc.get("description"),
                    image=pick_product_image(doc.get("source_url"), doc.get("blob_url")),
                    category_path=doc.get("category_path"),
                    score=doc.get("@search.score"),
                )
            )
        return cards

    @staticmethod
    def _post_filter(cards: list[ProductCard]) -> list[ProductCard]:
        out: list[ProductCard] = []
        for card in cards:
            if looks_like_gift_card(card.name, card.description):
                continue
            # Prefer items with a usable public image; keep a few without as last resort.
            out.append(card)
        # Stable: items with images first.
        with_image = [c for c in out if c.image]
        without = [c for c in out if not c.image]
        return with_image + without

    def ping(self) -> bool:
        endpoint = self.settings.azure_search_endpoint.rstrip("/")
        index = self.settings.azure_search_index_name
        url = f"{endpoint}/indexes/{index}?api-version=2024-07-01"
        headers = {"api-key": self.settings.search_api_key}
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, headers=headers)
            return response.status_code == 200
