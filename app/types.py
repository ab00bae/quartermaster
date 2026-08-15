"""Custom column types."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator):
    """A timestamp that is always UTC-aware in Python, on write and on read.

    SQLite has no native timezone storage, so a plain ``DateTime(timezone=True)``
    column accepts an aware datetime and hands back a naive one. That makes the
    API serialise the same instant two different ways depending on whether the
    row was just created or loaded from disk. This decorator normalises both
    directions so the contract holds on every backend.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Refusing to store a naive datetime; supply a UTC value.")
        return value.astimezone(timezone.utc)

    def process_result_value(
        self, value: datetime | None, dialect
    ) -> datetime | None:
        if value is None:
            return None
        # Naive here means the backend dropped the offset (SQLite); the value was
        # written as UTC, so label it as such rather than guessing local time.
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
