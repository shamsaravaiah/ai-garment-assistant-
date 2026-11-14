from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class IntentFilters(BaseModel):
    price_max: float | None = None
    price_min: float | None = None
    currency: str | None = None
    occasion: list[str] = Field(default_factory=list)
    style: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    gender: str | None = None
    garment_type: str | None = None
    season: list[str] = Field(default_factory=list)
    retrieval_query: str = ""
    needs_clarification: bool = False
    clarifying_question: str | None = None
    missing_slots: list[str] = Field(default_factory=list)

    def merge(self, newer: IntentFilters) -> IntentFilters:
        """Merge prior filters with a newly parsed turn (newer wins when set)."""
        return IntentFilters(
            price_max=newer.price_max if newer.price_max is not None else self.price_max,
            price_min=newer.price_min if newer.price_min is not None else self.price_min,
            currency=newer.currency or self.currency,
            occasion=newer.occasion or self.occasion,
            style=newer.style or self.style,
            colors=newer.colors or self.colors,
            gender=newer.gender or self.gender,
            garment_type=newer.garment_type or self.garment_type,
            season=newer.season or self.season,
            retrieval_query=newer.retrieval_query or self.retrieval_query,
            needs_clarification=newer.needs_clarification,
            clarifying_question=(
                newer.clarifying_question if newer.needs_clarification else None
            ),
            missing_slots=newer.missing_slots
            if newer.needs_clarification
            else [],
        )

    def specificity_score(self) -> int:
        score = 0
        if self.garment_type:
            score += 2
        if self.occasion:
            score += 2
        if self.colors:
            score += 1
        if self.style:
            score += 1
        if self.gender:
            score += 1
        if self.price_max is not None:
            score += 1
        if self.retrieval_query and len(self.retrieval_query.split()) >= 4:
            score += 1
        return score


class ProductCard(BaseModel):
    product_id: str
    name: str | None = None
    brand: str | None = None
    price: float | None = None
    currency: str | None = None
    description: str | None = None
    image: str | None = None
    url: str | None = None
    category_path: str | None = None
    score: float | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: UUID | None = None
    top_k: int | None = Field(default=None, ge=1, le=10)


class ChatResponse(BaseModel):
    session_id: UUID
    reply: str
    products: list[ProductCard]
    filters_applied: IntentFilters
    needs_clarification: bool = False


class ChatMessageOut(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    products: list[ProductCard] | None = None
    created_at: str | None = None


class SessionHistoryResponse(BaseModel):
    session_id: UUID
    summary: str | None = None
    filters: IntentFilters | None = None
    messages: list[ChatMessageOut]


class HealthResponse(BaseModel):
    status: str
    checks: dict[str, Any]
