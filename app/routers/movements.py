"""Stock movement routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.routers.deps import ServiceDep
from app.schemas import ErrorResponse, MovementCreate, MovementRead

router = APIRouter(tags=["movements"])


@router.post(
    "/items/{item_id}/movements",
    response_model=MovementRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record a stock movement",
    description=(
        "Applies a signed change to the item's quantity and appends an audit "
        "record. Rejected with 409 INSUFFICIENT_STOCK if it would take the "
        "quantity below zero."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "Item not found"},
        409: {"model": ErrorResponse, "description": "Would take quantity below zero"},
    },
)
def record_movement(
    item_id: int, payload: MovementCreate, service: ServiceDep
) -> MovementRead:
    return service.record_movement(item_id, payload)


@router.get(
    "/items/{item_id}/movements",
    response_model=list[MovementRead],
    summary="Audit log for one item",
    responses={404: {"model": ErrorResponse, "description": "Item not found"}},
)
def list_item_movements(
    item_id: int,
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MovementRead]:
    return service.list_movements(item_id=item_id, limit=limit, offset=offset)


@router.get(
    "/movements",
    response_model=list[MovementRead],
    summary="Audit log across all items",
)
def list_movements(
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MovementRead]:
    return service.list_movements(limit=limit, offset=offset)
