"""Integration tests for stock movements — including the headline business rule."""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestRecordMovement:
    def test_receipt_increases_quantity(self, client: TestClient, anchor: dict):
        response = client.post(
            f"/items/{anchor['id']}/movements",
            json={"delta": 5, "reason": "receipt", "note": "restock"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["delta"] == 5
        assert body["quantity_after"] == 15
        assert body["note"] == "restock"
        assert client.get(f"/items/{anchor['id']}").json()["quantity"] == 15

    def test_sale_decreases_quantity(self, client: TestClient, anchor: dict):
        response = client.post(
            f"/items/{anchor['id']}/movements", json={"delta": -4, "reason": "sale"}
        )

        assert response.status_code == 201
        assert response.json()["quantity_after"] == 6

    def test_drawing_stock_to_exactly_zero_succeeds(
        self, client: TestClient, anchor: dict
    ):
        response = client.post(
            f"/items/{anchor['id']}/movements", json={"delta": -10, "reason": "sale"}
        )

        assert response.status_code == 201
        assert response.json()["quantity_after"] == 0

    def test_oversell_is_rejected_with_409(self, client: TestClient, anchor: dict):
        response = client.post(
            f"/items/{anchor['id']}/movements", json={"delta": -11, "reason": "sale"}
        )

        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "INSUFFICIENT_STOCK"
        assert error["details"] == {
            "sku": "ANCHOR-001",
            "requested": -11,
            "available": 10,
        }

    def test_rejected_oversell_does_not_change_stock(
        self, client: TestClient, anchor: dict
    ):
        client.post(
            f"/items/{anchor['id']}/movements", json={"delta": -11, "reason": "sale"}
        )

        assert client.get(f"/items/{anchor['id']}").json()["quantity"] == 10

    def test_zero_delta_is_rejected(self, client: TestClient, anchor: dict):
        response = client.post(
            f"/items/{anchor['id']}/movements", json={"delta": 0, "reason": "adjustment"}
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_unknown_reason_is_rejected(self, client: TestClient, anchor: dict):
        response = client.post(
            f"/items/{anchor['id']}/movements",
            json={"delta": 1, "reason": "teleported"},
        )

        assert response.status_code == 422

    def test_movement_on_unknown_item_returns_404(self, client: TestClient):
        response = client.post(
            "/items/999/movements", json={"delta": 1, "reason": "receipt"}
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "ITEM_NOT_FOUND"


class TestAuditLog:
    def test_opening_balance_is_the_first_entry(self, client: TestClient, anchor: dict):
        log = client.get(f"/items/{anchor['id']}/movements").json()

        assert len(log) == 1
        assert log[0]["delta"] == 10
        assert log[0]["note"] == "opening balance"

    def test_entries_are_newest_first(self, client: TestClient, anchor: dict):
        client.post(f"/items/{anchor['id']}/movements",
                    json={"delta": -2, "reason": "sale"})
        client.post(f"/items/{anchor['id']}/movements",
                    json={"delta": -3, "reason": "sale"})

        log = client.get(f"/items/{anchor['id']}/movements").json()

        assert [entry["delta"] for entry in log] == [-3, -2, 10]
        assert [entry["quantity_after"] for entry in log] == [5, 8, 10]

    def test_log_for_unknown_item_returns_404_not_an_empty_list(
        self, client: TestClient
    ):
        """A typo in the id should not look like an item that never moved."""
        assert client.get("/items/999/movements").status_code == 404

    def test_item_with_no_movements_returns_an_empty_list(self, client: TestClient):
        response = client.post(
            "/items", json={"sku": "EMPTY-1", "name": "Empty", "location": "HOLD-A"}
        )
        item_id = response.json()["id"]

        assert client.get(f"/items/{item_id}/movements").json() == []

    def test_global_log_spans_every_item(self, client: TestClient, anchor: dict):
        second = client.post(
            "/items",
            json={"sku": "ROPE-050", "name": "Rope", "location": "HOLD-A",
                  "quantity": 5},
        ).json()
        client.post(f"/items/{second['id']}/movements",
                    json={"delta": -1, "reason": "sale"})

        log = client.get("/movements").json()

        assert len(log) == 3
        assert {entry["item_id"] for entry in log} == {anchor["id"], second["id"]}

    def test_global_log_pagination(self, client: TestClient, anchor: dict):
        for _ in range(4):
            client.post(f"/items/{anchor['id']}/movements",
                        json={"delta": -1, "reason": "sale"})

        page = client.get("/movements", params={"limit": 2, "offset": 1}).json()

        assert len(page) == 2
        assert [entry["quantity_after"] for entry in page] == [7, 8]
