from __future__ import annotations

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.models.schemas import ProductCard


class ProductHydrator:
    """Fill product_url / primary image from Postgres by product_id."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def hydrate(self, cards: list[ProductCard]) -> list[ProductCard]:
        if not cards:
            return cards

        ids = [c.product_id for c in cards]
        stmt = text(
            """
            SELECT
                p.id::text AS product_id,
                p.name,
                p.brand,
                p.price,
                p.currency,
                p.product_url,
                p.category_path,
                img.source_url AS image_source_url,
                img.blob_url AS image_blob_url
            FROM products p
            LEFT JOIN LATERAL (
                SELECT source_url, blob_url
                FROM product_images pi
                WHERE pi.product_id = p.id
                ORDER BY pi.position ASC NULLS LAST, pi.id ASC
                LIMIT 1
            ) img ON TRUE
            WHERE p.id::text IN :ids
            """
        ).bindparams(bindparam("ids", expanding=True))

        try:
            rows = self.db.execute(stmt, {"ids": ids}).mappings().all()
        except Exception:
            # Catalog tables may be unreachable; return Search cards as-is.
            self.db.rollback()
            return cards

        by_id = {row["product_id"]: row for row in rows}

        hydrated: list[ProductCard] = []
        for card in cards:
            row = by_id.get(card.product_id)
            if not row:
                hydrated.append(card)
                continue
            hydrated.append(
                ProductCard(
                    product_id=card.product_id,
                    name=card.name or row.get("name"),
                    brand=card.brand or row.get("brand"),
                    price=card.price if card.price is not None else row.get("price"),
                    currency=card.currency or row.get("currency"),
                    description=card.description,
                    image=(
                        card.image
                        or row.get("image_source_url")
                        or row.get("image_blob_url")
                    ),
                    url=row.get("product_url"),
                    category_path=card.category_path or row.get("category_path"),
                    score=card.score,
                )
            )
        return hydrated
