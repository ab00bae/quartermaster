"""Integration tests for the item routes, through the real HTTP stack."""

from __future__ import annotations

from fastapi.testclient import TestClient

NEW_ITEM = {
    "sku": "ROPE-050",
    "name": "Nylon Dock Line 15m",
    "quantity": 60,
    "location": "HOLD-A",
    "reorder_threshold": 20,
}


class TestCreate:
    def test_returns_201_with_the_created_item(self, client: TestClient):
        response = client.post("/items", json=NEW_ITEM)

        assert response.status_code == 201
        body = response.json()
        assert body["sku"] == "ROPE-050"
        assert body["quantity"] == 60
        assert body["low_stock"] is False
        assert isinstance(body["id"], int)

    def test_quantity_and_threshold_default_to_zero(self, client: TestClient):
        response = client.post(
            "/items", json={"sku": "BARE-1", "name": "Bare", "location": "HOLD-A"}
        )

        assert response.status_code == 201
        assert response.json()["quantity"] == 0
        assert response.json()["reorder_threshold"] == 0

    def test_duplicate_sku_returns_409(self, client: TestClient):
        client.post("/items", json=NEW_ITEM)

        response = client.post("/items", json=NEW_ITEM)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "DUPLICATE_SKU"

    def test_negative_quantity_is_rejected(self, client: TestClient):
        response = client.post("/items", json={**NEW_ITEM, "quantity": -1})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_blank_sku_is_rejected(self, client: TestClient):
        response = client.post("/items", json={**NEW_ITEM, "sku": ""})

        assert response.status_code == 422


class TestRead:
    def test_get_returns_the_item(self, client: TestClient, anchor: dict):
        response = client.get(f"/items/{anchor['id']}")

        assert response.status_code == 200
        assert response.json()["sku"] == "ANCHOR-001"

    def test_get_unknown_id_returns_404_in_the_error_envelope(
        self, client: TestClient
    ):
        response = client.get("/items/999")

        assert response.status_code == 404
        error = response.json()["error"]
        assert error["code"] == "ITEM_NOT_FOUND"
        assert error["details"]["item_id"] == 999

    def test_timestamps_are_utc_on_create_and_on_read(
        self, client: TestClient, anchor: dict
    ):
        """A regression guard: SQLite drops the offset, so read-back must re-apply it."""
        fetched = client.get(f"/items/{anchor['id']}").json()

        assert anchor["created_at"].endswith("Z")
        assert fetched["created_at"].endswith("Z")
        assert fetched["created_at"] == anchor["created_at"]


class TestList:
    def test_lists_all_items(self, client: TestClient, anchor: dict):
        client.post("/items", json=NEW_ITEM)

        response = client.get("/items")

        assert response.status_code == 200
        assert {i["sku"] for i in response.json()} == {"ANCHOR-001", "ROPE-050"}

    def test_filters_by_location(self, client: TestClient, anchor: dict):
        client.post("/items", json={**NEW_ITEM, "location": "LOCKER-1"})

        response = client.get("/items", params={"location": "LOCKER-1"})

        assert [i["sku"] for i in response.json()] == ["ROPE-050"]

    def test_filters_by_low_stock(self, client: TestClient, anchor: dict):
        client.post(
            "/items",
            json={"sku": "LOW-1", "name": "Low", "location": "HOLD-A",
                  "quantity": 1, "reorder_threshold": 5},
        )

        low = client.get("/items", params={"low_stock": True}).json()

        assert [i["sku"] for i in low] == ["LOW-1"]

    def test_pagination(self, client: TestClient):
        for n in range(5):
            client.post(
                "/items",
                json={"sku": f"SKU-{n}", "name": f"Item {n}", "location": "HOLD-A"},
            )

        page = client.get("/items", params={"limit": 2, "offset": 2}).json()

        assert [i["sku"] for i in page] == ["SKU-2", "SKU-3"]

    def test_limit_above_the_cap_is_rejected(self, client: TestClient):
        assert client.get("/items", params={"limit": 500}).status_code == 422


class TestUpdate:
    def test_patch_updates_only_supplied_fields(self, client: TestClient, anchor: dict):
        response = client.patch(
            f"/items/{anchor['id']}", json={"location": "LOCKER-1"}
        )

        assert response.status_code == 200
        assert response.json()["location"] == "LOCKER-1"
        assert response.json()["name"] == anchor["name"]

    def test_quantity_cannot_be_patched(self, client: TestClient, anchor: dict):
        """Stock only moves through a movement, so this field is ignored."""
        response = client.patch(f"/items/{anchor['id']}", json={"quantity": 999})

        assert response.status_code == 200
        assert response.json()["quantity"] == anchor["quantity"]

    def test_patch_unknown_id_returns_404(self, client: TestClient):
        assert client.patch("/items/999", json={"name": "ghost"}).status_code == 404


class TestDelete:
    def test_delete_returns_204(self, client: TestClient, anchor: dict):
        assert client.delete(f"/items/{anchor['id']}").status_code == 204
        assert client.get(f"/items/{anchor['id']}").status_code == 404

    def test_delete_cascades_to_the_audit_log(self, client: TestClient, anchor: dict):
        item_id = anchor["id"]
        client.post(f"/items/{item_id}/movements", json={"delta": -1, "reason": "sale"})

        client.delete(f"/items/{item_id}")

        assert client.get("/movements").json() == []

    def test_delete_unknown_id_returns_404(self, client: TestClient):
        assert client.delete("/items/999").status_code == 404


class TestOps:
    def test_health(self, client: TestClient):
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_openapi_schema_is_generated(self, client: TestClient):
        schema = client.get("/openapi.json").json()

        assert schema["info"]["title"] == "Quartermaster"
        assert "/items/{item_id}/movements" in schema["paths"]
