"""Domain errors.

The service layer raises these; the HTTP layer is the only place that knows they
map onto status codes. That keeps the business rules independent of FastAPI.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for expected, client-correctable failures."""

    code: str = "DOMAIN_ERROR"
    status_code: int = 400

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class ItemNotFound(DomainError):
    code = "ITEM_NOT_FOUND"
    status_code = 404


class DuplicateSku(DomainError):
    code = "DUPLICATE_SKU"
    status_code = 409


class InsufficientStock(DomainError):
    """Raised when a movement would drive an item's quantity below zero."""

    code = "INSUFFICIENT_STOCK"
    status_code = 409
