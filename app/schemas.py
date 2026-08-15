"""Pydantic request/response models.

These are the API's contract. They are deliberately separate from the ORM models
so that the storage schema can change without silently reshaping the API.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import MovementReason


class ItemCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64, examples=["ANCHOR-001"])
    name: str = Field(min_length=1, max_length=255, examples=["Danforth Anchor 8kg"])
    quantity: int = Field(default=0, ge=0)
    location: str = Field(min_length=1, max_length=64, examples=["HOLD-A"])
    reorder_threshold: int = Field(default=0, ge=0)

    @field_validator("sku")
    @classmethod
    def normalise_sku(cls, value: str) -> str:
        # SKUs are matched exactly and are case-insensitive in practice, so they
        # are stored in one canonical form rather than trusting the caller.
        return value.strip().upper()


class ItemUpdate(BaseModel):
    """Partial update.

    Quantity is intentionally absent: stock only moves through a recorded
    movement, so there is no way to change it without leaving an audit trail.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    location: str | None = Field(default=None, min_length=1, max_length=64)
    reorder_threshold: int | None = Field(default=None, ge=0)


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    quantity: int
    location: str
    reorder_threshold: int
    low_stock: bool
    created_at: datetime
    updated_at: datetime


class MovementCreate(BaseModel):
    delta: int = Field(
        description="Signed change in quantity. Negative removes stock.",
        examples=[-3],
    )
    reason: MovementReason
    note: str | None = Field(default=None, max_length=255)

    @field_validator("delta")
    @classmethod
    def reject_zero_delta(cls, value: int) -> int:
        if value == 0:
            raise ValueError("delta must be non-zero")
        return value


class MovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_id: int
    delta: int
    reason: MovementReason
    quantity_after: int
    note: str | None
    created_at: datetime


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Every handled failure comes back in this shape, so clients can branch on
    `error.code` instead of parsing prose."""

    error: ErrorBody
