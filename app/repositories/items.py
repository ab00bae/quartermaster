"""Item persistence.

Queries and writes only — no business rules, and no commits. The service layer
owns the transaction boundary so that an item update and its audit record either
land together or not at all.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Item


class ItemRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, item_id: int) -> Item | None:
        return self.db.get(Item, item_id)

    def get_by_sku(self, sku: str) -> Item | None:
        return self.db.scalar(select(Item).where(Item.sku == sku))

    def list(
        self,
        *,
        location: str | None = None,
        low_stock: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Item]:
        stmt = select(Item).order_by(Item.id)

        if location is not None:
            stmt = stmt.where(Item.location == location)

        if low_stock is not None:
            # Expressed in SQL rather than filtering in Python so the database
            # does the work and pagination stays correct.
            condition = Item.quantity <= Item.reorder_threshold
            stmt = stmt.where(condition if low_stock else ~condition)

        return list(self.db.scalars(stmt.limit(limit).offset(offset)))

    def add(self, item: Item) -> Item:
        self.db.add(item)
        self.db.flush()
        return item

    def delete(self, item: Item) -> None:
        self.db.delete(item)
        self.db.flush()
