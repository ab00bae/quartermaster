"""Stock movement persistence — append and read only, by design."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StockMovement


class MovementRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, movement: StockMovement) -> StockMovement:
        self.db.add(movement)
        self.db.flush()
        return movement

    def list(
        self,
        *,
        item_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[StockMovement]:
        # Newest first: an audit log is almost always read from the present
        # backwards.
        stmt = select(StockMovement).order_by(StockMovement.id.desc())

        if item_id is not None:
            stmt = stmt.where(StockMovement.item_id == item_id)

        return list(self.db.scalars(stmt.limit(limit).offset(offset)))
