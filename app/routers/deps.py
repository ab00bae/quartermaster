"""Shared route dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.inventory import InventoryService


def get_inventory_service(
    db: Annotated[Session, Depends(get_db)],
) -> InventoryService:
    return InventoryService(db)


ServiceDep = Annotated[InventoryService, Depends(get_inventory_service)]
