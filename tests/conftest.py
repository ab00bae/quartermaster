"""Shared test fixtures.

Every test gets its own in-memory database, so tests neither share state nor
depend on a running PostgreSQL. StaticPool keeps all connections pointed at the
same in-memory database, which SQLite otherwise gives per connection.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  - registers tables on Base.metadata
from app.db import Base, get_db
from app.main import create_app
from app.services.inventory import InventoryService


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def service(db: Session) -> InventoryService:
    """The service under test, with no HTTP layer in the way."""
    return InventoryService(db)


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    app = create_app()

    def override_get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def anchor(client: TestClient) -> dict:
    """A created item most tests can start from."""
    response = client.post(
        "/items",
        json={
            "sku": "ANCHOR-001",
            "name": "Danforth Anchor 8kg",
            "quantity": 10,
            "location": "HOLD-A",
            "reorder_threshold": 3,
        },
    )
    assert response.status_code == 201
    return response.json()
