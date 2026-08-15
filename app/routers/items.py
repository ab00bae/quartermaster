"""Item routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.routers.deps import ServiceDep
from app.schemas import ErrorResponse, ItemCreate, ItemRead, ItemUpdate

router = APIRouter(prefix="/items", tags=["items"])


@router.post(
    "",
    response_model=ItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an item",
    responses={409: {"model": ErrorResponse, "description": "SKU already exists"}},
)
def create_item(payload: ItemCreate, service: ServiceDep) -> ItemRead:
    return service.create_item(payload)


@router.get("", response_model=list[ItemRead], summary="List items")
def list_items(
    service: ServiceDep,
    location: Annotated[str | None, Query(description="Filter by location code")] = None,
    low_stock: Annotated[
        bool | None,
        Query(description="Only items at or under their reorder threshold"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ItemRead]:
    return service.list_items(
        location=location, low_stock=low_stock, limit=limit, offset=offset
    )


@router.get(
    "/{item_id}",
    response_model=ItemRead,
    summary="Get one item",
    responses={404: {"model": ErrorResponse, "description": "Item not found"}},
)
def get_item(item_id: int, service: ServiceDep) -> ItemRead:
    return service.get_item(item_id)


@router.patch(
    "/{item_id}",
    response_model=ItemRead,
    summary="Update an item's details",
    description=(
        "Quantity cannot be set here — it only changes through a stock movement, "
        "so every change keeps an audit trail."
    ),
    responses={404: {"model": ErrorResponse, "description": "Item not found"}},
)
def update_item(item_id: int, payload: ItemUpdate, service: ServiceDep) -> ItemRead:
    return service.update_item(item_id, payload)


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an item and its movement history",
    responses={404: {"model": ErrorResponse, "description": "Item not found"}},
)
def delete_item(item_id: int, service: ServiceDep) -> None:
    service.delete_item(item_id)
