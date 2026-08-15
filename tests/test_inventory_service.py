"""Unit tests for the business rules, exercised without the HTTP layer."""

from __future__ import annotations

import pytest

from app.errors import DuplicateSku, InsufficientStock, ItemNotFound
from app.models import MovementReason
from app.schemas import ItemCreate, ItemUpdate, MovementCreate
from app.services.inventory import InventoryService


def make_item(service: InventoryService, **overrides) -> object:
    payload = {
        "sku": "ANCHOR-001",
        "name": "Danforth Anchor 8kg",
        "quantity": 10,
        "location": "HOLD-A",
        "reorder_threshold": 3,
    }
    payload.update(overrides)
    return service.create_item(ItemCreate(**payload))


class TestItemCreation:
    def test_opening_stock_is_recorded_as_a_movement(self, service: InventoryService):
        item = make_item(service, quantity=10)

        movements = service.list_movements(item_id=item.id)

        assert len(movements) == 1
        assert movements[0].delta == 10
        assert movements[0].quantity_after == 10
        assert movements[0].reason == MovementReason.RECEIPT.value
        assert movements[0].note == "opening balance"

    def test_item_created_empty_has_no_movements(self, service: InventoryService):
        item = make_item(service, quantity=0)

        assert service.list_movements(item_id=item.id) == []

    def test_sku_is_normalised_to_uppercase(self, service: InventoryService):
        item = make_item(service, sku="anchor-001")

        assert item.sku == "ANCHOR-001"

    def test_duplicate_sku_is_rejected(self, service: InventoryService):
        make_item(service)

        with pytest.raises(DuplicateSku) as exc_info:
            make_item(service, name="A different anchor")

        assert exc_info.value.details["sku"] == "ANCHOR-001"

    def test_duplicate_check_is_case_insensitive(self, service: InventoryService):
        """Normalisation happens before the uniqueness check, not after."""
        make_item(service, sku="ANCHOR-001")

        with pytest.raises(DuplicateSku):
            make_item(service, sku="anchor-001")


class TestStockMovements:
    def test_positive_movement_increases_quantity(self, service: InventoryService):
        item = make_item(service, quantity=10)

        movement = service.record_movement(
            item.id, MovementCreate(delta=5, reason=MovementReason.RECEIPT)
        )

        assert movement.quantity_after == 15
        assert service.get_item(item.id).quantity == 15

    def test_negative_movement_decreases_quantity(self, service: InventoryService):
        item = make_item(service, quantity=10)

        movement = service.record_movement(
            item.id, MovementCreate(delta=-4, reason=MovementReason.SALE)
        )

        assert movement.quantity_after == 6
        assert service.get_item(item.id).quantity == 6

    def test_movement_to_exactly_zero_is_allowed(self, service: InventoryService):
        """Zero is a legal resting quantity — only negative is forbidden."""
        item = make_item(service, quantity=10)

        movement = service.record_movement(
            item.id, MovementCreate(delta=-10, reason=MovementReason.SALE)
        )

        assert movement.quantity_after == 0

    def test_movement_below_zero_is_rejected(self, service: InventoryService):
        item = make_item(service, quantity=10)

        with pytest.raises(InsufficientStock) as exc_info:
            service.record_movement(
                item.id, MovementCreate(delta=-11, reason=MovementReason.SALE)
            )

        assert exc_info.value.details == {
            "sku": "ANCHOR-001",
            "requested": -11,
            "available": 10,
        }

    def test_rejected_movement_leaves_no_trace(self, service: InventoryService):
        """The rule must not half-apply: no quantity change, no audit row."""
        item = make_item(service, quantity=10)
        movements_before = len(service.list_movements(item_id=item.id))

        with pytest.raises(InsufficientStock):
            service.record_movement(
                item.id, MovementCreate(delta=-99, reason=MovementReason.SALE)
            )

        assert service.get_item(item.id).quantity == 10
        assert len(service.list_movements(item_id=item.id)) == movements_before

    def test_movement_against_unknown_item_raises(self, service: InventoryService):
        with pytest.raises(ItemNotFound):
            service.record_movement(
                999, MovementCreate(delta=1, reason=MovementReason.RECEIPT)
            )

    def test_audit_log_is_newest_first(self, service: InventoryService):
        item = make_item(service, quantity=10)
        service.record_movement(
            item.id, MovementCreate(delta=-2, reason=MovementReason.SALE)
        )
        service.record_movement(
            item.id, MovementCreate(delta=-3, reason=MovementReason.SALE)
        )

        deltas = [m.delta for m in service.list_movements(item_id=item.id)]

        assert deltas == [-3, -2, 10]

    def test_audit_log_reconstructs_current_quantity(self, service: InventoryService):
        """The log is complete enough to be replayed."""
        item = make_item(service, quantity=10)
        service.record_movement(
            item.id, MovementCreate(delta=-4, reason=MovementReason.SALE)
        )
        service.record_movement(
            item.id, MovementCreate(delta=7, reason=MovementReason.RECEIPT)
        )

        replayed = sum(m.delta for m in service.list_movements(item_id=item.id))

        assert replayed == service.get_item(item.id).quantity == 13


class TestLowStockFlag:
    @pytest.mark.parametrize(
        ("quantity", "threshold", "expected"),
        [
            (10, 3, False),  # comfortably above
            (4, 3, False),  # one above the threshold
            (3, 3, True),  # exactly at the threshold counts as low
            (2, 3, True),  # below
            (0, 0, True),  # empty with no threshold set is still low
            (1, 0, False),
        ],
    )
    def test_boundary(
        self,
        service: InventoryService,
        quantity: int,
        threshold: int,
        expected: bool,
    ):
        item = make_item(service, quantity=quantity, reorder_threshold=threshold)

        assert item.low_stock is expected

    def test_filter_returns_only_low_items(self, service: InventoryService):
        make_item(service, sku="HIGH", quantity=50, reorder_threshold=5)
        make_item(service, sku="LOW", quantity=2, reorder_threshold=5)

        low = service.list_items(low_stock=True)
        not_low = service.list_items(low_stock=False)

        assert [i.sku for i in low] == ["LOW"]
        assert [i.sku for i in not_low] == ["HIGH"]

    def test_movement_can_flip_an_item_into_low_stock(self, service: InventoryService):
        item = make_item(service, quantity=10, reorder_threshold=3)
        assert item.low_stock is False

        service.record_movement(
            item.id, MovementCreate(delta=-8, reason=MovementReason.SALE)
        )

        assert service.get_item(item.id).low_stock is True


class TestItemUpdates:
    def test_partial_update_leaves_other_fields_alone(self, service: InventoryService):
        item = make_item(service, name="Old name", location="HOLD-A")

        updated = service.update_item(item.id, ItemUpdate(name="New name"))

        assert updated.name == "New name"
        assert updated.location == "HOLD-A"

    def test_update_cannot_change_quantity(self, service: InventoryService):
        """Quantity is not part of the update contract, so it cannot be smuggled in."""
        item = make_item(service, quantity=10)

        service.update_item(item.id, ItemUpdate.model_validate({"quantity": 999}))

        assert service.get_item(item.id).quantity == 10

    def test_raising_threshold_can_flag_an_item_low(self, service: InventoryService):
        item = make_item(service, quantity=5, reorder_threshold=1)

        updated = service.update_item(item.id, ItemUpdate(reorder_threshold=5))

        assert updated.low_stock is True

    def test_update_unknown_item_raises(self, service: InventoryService):
        with pytest.raises(ItemNotFound):
            service.update_item(999, ItemUpdate(name="ghost"))


class TestItemDeletion:
    def test_delete_removes_item_and_its_movements(self, service: InventoryService):
        item = make_item(service, quantity=10)
        item_id = item.id

        service.delete_item(item_id)

        with pytest.raises(ItemNotFound):
            service.get_item(item_id)
        assert service.movements.list(item_id=item_id) == []

    def test_delete_unknown_item_raises(self, service: InventoryService):
        with pytest.raises(ItemNotFound):
            service.delete_item(999)
