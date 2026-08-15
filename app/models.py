"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.types import UtcDateTime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MovementReason(str, Enum):
    """Why stock moved. Kept small and closed so reports can group on it."""

    RECEIPT = "receipt"
    SALE = "sale"
    ADJUSTMENT = "adjustment"
    DAMAGE = "damage"
    TRANSFER = "transfer"


class Item(Base):
    """A stocked item at a single location."""

    __tablename__ = "items"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_items_quantity_non_negative"),
        CheckConstraint(
            "reorder_threshold >= 0", name="ck_items_reorder_threshold_non_negative"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    location: Mapped[str] = mapped_column(String(64), index=True)
    reorder_threshold: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow
    )

    movements: Mapped[list["StockMovement"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def low_stock(self) -> bool:
        """True when stock has fallen to or below the reorder threshold."""
        return self.quantity <= self.reorder_threshold


class StockMovement(Base):
    """An append-only audit record of one change to an item's quantity.

    Rows are never updated or deleted through the API — correcting a mistake
    means recording a compensating movement, which is what an audit log is for.
    """

    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint("delta <> 0", name="ck_stock_movements_delta_non_zero"),
        Index("ix_stock_movements_item_id_id", "item_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(32))
    quantity_after: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    item: Mapped["Item"] = relationship(back_populates="movements")
