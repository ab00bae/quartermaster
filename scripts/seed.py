"""Populate the database with sample stock.

Idempotent: re-running skips SKUs that already exist, so it is safe to point at
a database that has already been seeded. Run migrations first.

    alembic upgrade head
    python -m scripts.seed
"""

from __future__ import annotations

from app.db import SessionLocal
from app.errors import DuplicateSku
from app.models import MovementReason
from app.schemas import ItemCreate, MovementCreate
from app.services.inventory import InventoryService

ITEMS: list[ItemCreate] = [
    ItemCreate(sku="ANCHOR-001", name="Danforth Anchor 8kg", quantity=12,
               location="HOLD-A", reorder_threshold=4),
    ItemCreate(sku="ROPE-050", name="Nylon Dock Line 15m", quantity=60,
               location="HOLD-A", reorder_threshold=20),
    ItemCreate(sku="FLARE-RED", name="Red Handheld Flare", quantity=8,
               location="LOCKER-1", reorder_threshold=8),
    ItemCreate(sku="VEST-L", name="Life Vest (Large)", quantity=25,
               location="LOCKER-1", reorder_threshold=10),
    ItemCreate(sku="BILGE-PUMP", name="Bilge Pump 800GPH", quantity=3,
               location="ENGINE-BAY", reorder_threshold=2),
    ItemCreate(sku="CHART-GL", name="Great Lakes Chart Set", quantity=1,
               location="BRIDGE", reorder_threshold=3),
]

# Applied after creation so the audit log has some history to show.
MOVEMENTS: list[tuple[str, MovementCreate]] = [
    ("ROPE-050", MovementCreate(delta=-12, reason=MovementReason.SALE,
                                note="outfitting slip 14")),
    ("VEST-L", MovementCreate(delta=-16, reason=MovementReason.SALE,
                              note="charter group")),
    ("ANCHOR-001", MovementCreate(delta=-9, reason=MovementReason.SALE,
                                  note="spring restock run")),
    ("FLARE-RED", MovementCreate(delta=4, reason=MovementReason.RECEIPT,
                                 note="safety resupply")),
    ("BILGE-PUMP", MovementCreate(delta=-1, reason=MovementReason.DAMAGE,
                                  note="cracked housing")),
]


def main() -> None:
    db = SessionLocal()
    service = InventoryService(db)
    created = skipped = 0

    try:
        by_sku = {}
        created_skus: set[str] = set()

        for payload in ITEMS:
            try:
                item = service.create_item(payload)
                created_skus.add(payload.sku)
                created += 1
            except DuplicateSku:
                item = service.items.get_by_sku(payload.sku)
                skipped += 1
            by_sku[payload.sku] = item

        for sku, movement in MOVEMENTS:
            # Sample history belongs only to items this run created. Keying off
            # anything else (such as current stock being sufficient) would draw
            # the same items down again on every re-run.
            if sku in created_skus:
                service.record_movement(by_sku[sku].id, movement)

        print(f"Seed complete: {created} item(s) created, {skipped} already present.")
        low = service.list_items(low_stock=True)
        print(f"Items at or under reorder threshold: {len(low)}")
        for item in low:
            print(f"  {item.sku:<12} {item.quantity:>4} / threshold {item.reorder_threshold}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
