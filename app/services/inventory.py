"""Inventory rules.

Two rules matter here, and both live in this file rather than in a route handler:

1. A stock movement may never drive an item's quantity below zero.
2. An item is flagged low when quantity <= reorder_threshold.

Every quantity change is written together with the movement that caused it, in
one transaction, so the audit log can never disagree with the stock on hand.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import DuplicateSku, InsufficientStock, ItemNotFound
from app.models import Item, MovementReason, StockMovement
from app.repositories.items import ItemRepository
from app.repositories.movements import MovementRepository
from app.schemas import ItemCreate, ItemUpdate, MovementCreate


class InventoryService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.items = ItemRepository(db)
        self.movements = MovementRepository(db)

    # -- items ---------------------------------------------------------------

    def create_item(self, payload: ItemCreate) -> Item:
        if self.items.get_by_sku(payload.sku) is not None:
            raise DuplicateSku(
                f"An item with SKU {payload.sku} already exists.", sku=payload.sku
            )

        item = Item(
            sku=payload.sku,
            name=payload.name,
            quantity=payload.quantity,
            location=payload.location,
            reorder_threshold=payload.reorder_threshold,
        )

        try:
            self.items.add(item)

            # An item that starts with stock still needs a first audit row,
            # otherwise the movement history cannot reconstruct the quantity.
            if payload.quantity > 0:
                self.movements.add(
                    StockMovement(
                        item_id=item.id,
                        delta=payload.quantity,
                        reason=MovementReason.RECEIPT.value,
                        quantity_after=payload.quantity,
                        note="opening balance",
                    )
                )

            self.db.commit()
        except IntegrityError as exc:
            # The pre-check above loses to a concurrent insert; the unique index
            # is the real guarantee, so translate its error rather than 500.
            self.db.rollback()
            raise DuplicateSku(
                f"An item with SKU {payload.sku} already exists.", sku=payload.sku
            ) from exc

        return item

    def get_item(self, item_id: int) -> Item:
        item = self.items.get(item_id)
        if item is None:
            raise ItemNotFound(f"No item with id {item_id}.", item_id=item_id)
        return item

    def list_items(
        self,
        *,
        location: str | None = None,
        low_stock: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Item]:
        return self.items.list(
            location=location, low_stock=low_stock, limit=limit, offset=offset
        )

    def update_item(self, item_id: int, payload: ItemUpdate) -> Item:
        item = self.get_item(item_id)

        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(item, field, value)

        self.db.commit()
        return item

    def delete_item(self, item_id: int) -> None:
        item = self.get_item(item_id)
        self.items.delete(item)
        self.db.commit()

    # -- movements -----------------------------------------------------------

    def record_movement(self, item_id: int, payload: MovementCreate) -> StockMovement:
        """Apply a signed stock change and log it. Rule 1 is enforced here."""
        item = self.get_item(item_id)
        new_quantity = item.quantity + payload.delta

        if new_quantity < 0:
            raise InsufficientStock(
                f"Cannot move {payload.delta} of SKU {item.sku}: "
                f"only {item.quantity} in stock.",
                sku=item.sku,
                requested=payload.delta,
                available=item.quantity,
            )

        item.quantity = new_quantity
        movement = self.movements.add(
            StockMovement(
                item_id=item.id,
                delta=payload.delta,
                reason=payload.reason.value,
                quantity_after=new_quantity,
                note=payload.note,
            )
        )

        self.db.commit()
        return movement

    def list_movements(
        self,
        *,
        item_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[StockMovement]:
        if item_id is not None:
            # Surface a 404 for an unknown item rather than an empty list, so a
            # typo in the id is distinguishable from an item that never moved.
            self.get_item(item_id)

        return self.movements.list(item_id=item_id, limit=limit, offset=offset)
