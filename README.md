# quartermaster

[![ci](https://github.com/ab00bae/quartermaster/actions/workflows/ci.yml/badge.svg)](https://github.com/ab00bae/quartermaster/actions/workflows/ci.yml)

An inventory and stock-movement API. Items carry a SKU, quantity, location and
reorder threshold; every change to a quantity is written to an append-only audit
log, and a movement that would take stock below zero is rejected.

Built as a focused demonstration of backend API practice — layered architecture,
validation, migrations, and tests — rather than as a product.

```
POST /items/1/movements  {"delta": -99, "reason": "sale"}

409 Conflict
{
  "error": {
    "code": "INSUFFICIENT_STOCK",
    "message": "Cannot move -99 of SKU ANCHOR-001: only 3 in stock.",
    "details": { "sku": "ANCHOR-001", "requested": -99, "available": 3 }
  }
}
```

## What this demonstrates

| Practice | Where to look |
| --- | --- |
| Layered architecture — routes → services → repositories | [`app/routers/`](app/routers/), [`app/services/`](app/services/), [`app/repositories/`](app/repositories/) |
| Business rules isolated from the web framework | [`app/services/inventory.py`](app/services/inventory.py) |
| Request/response validation with Pydantic | [`app/schemas.py`](app/schemas.py) |
| Schema migrations, reversible and batch-safe | [`alembic/versions/`](alembic/versions/) |
| Unit tests (service, no HTTP) + integration tests (full stack) | [`tests/`](tests/) |
| Consistent machine-readable error contract | [`app/main.py`](app/main.py), [`app/errors.py`](app/errors.py) |
| Multi-stage Docker build, non-root runtime, healthcheck | [`Dockerfile`](Dockerfile) |
| Auto-generated OpenAPI documentation | `/docs` once running |

## Design decisions

**Quantity is never set directly.** `PATCH /items/{id}` cannot change a quantity —
only a recorded movement can. That keeps the audit log complete by construction
instead of by convention, so replaying every movement for an item always
reproduces its current stock. Creating an item with opening stock writes a
matching `receipt` movement for the same reason.

**The rule lives in the service layer.** `InventoryService.record_movement` both
checks the rule and writes the audit row inside a single transaction, so a
rejected movement cannot leave a partial change behind. The route handler only
translates HTTP; the rule is testable without a web server, and
`tests/test_inventory_service.py` tests it that way.

**Defence in depth on the invariant.** Non-negative stock is enforced in the
service *and* as a `CHECK` constraint in the database, so the invariant survives
a bug in the application or a write from outside it.

**Errors are typed, not stringly.** Every handled failure returns
`{"error": {"code", "message", "details"}}`, including framework validation
failures, which are reshaped into the same envelope. Clients branch on
`error.code` rather than parsing prose.

**Timestamps are always UTC-aware.** SQLite has no timezone storage, so a plain
timestamp column returns naive datetimes on read and the API would serialise the
same instant two ways. [`app/types.py`](app/types.py) normalises both directions.

## Architecture

```
        HTTP
         │
   ┌─────▼──────────────────────────────┐
   │ routers/      request → response   │  FastAPI, status codes, OpenAPI
   ├────────────────────────────────────┤
   │ services/     business rules       │  the two rules, transaction boundary
   ├────────────────────────────────────┤
   │ repositories/ data access          │  SQLAlchemy queries, no rules
   ├────────────────────────────────────┤
   │ models/       schema + constraints │  CHECK constraints, cascades
   └────────────────────────────────────┘
```

Each layer depends only on the one below it. The service layer imports no
FastAPI; the repository layer contains no business logic.

## Quickstart

Requires Python 3.11+.

```bash
git clone https://github.com/ab00bae/quartermaster.git
cd quartermaster

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

alembic upgrade head             # create the schema
python -m scripts.seed           # optional: load sample stock

uvicorn app.main:app --reload
```

Then open <http://127.0.0.1:8000/docs> for the generated API documentation.

By default the app uses a local SQLite file and needs no external services. To
run against PostgreSQL, set `DATABASE_URL` (see [`.env.example`](.env.example)):

```bash
export DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/quartermaster"
alembic upgrade head
```

## CLI demo

`demo.sh` starts the API against a throwaway database, exercises the full
contract with `curl`, and asserts on every response. It exits non-zero if any
check fails, so it doubles as a smoke test.

```bash
./demo.sh
```

```
The business rule: stock cannot go negative
  PASS  a sale larger than stock on hand is rejected
  PASS  error code is INSUFFICIENT_STOCK
  PASS  the error reports what was actually available
  PASS  the rejected movement left stock untouched
  PASS  and wrote no audit entry
  PASS  drawing down to exactly zero is allowed

Summary
  35/35 checks passed
```

## Tests

```bash
pytest
```

62 tests: business rules exercised directly against the service layer, plus
integration tests that drive the real HTTP stack. Each test gets its own
in-memory database, so the suite needs no running server or external database.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness probe |
| `POST` | `/items` | Create an item |
| `GET` | `/items` | List items — filter by `location`, `low_stock`; paginated |
| `GET` | `/items/{id}` | Fetch one item |
| `PATCH` | `/items/{id}` | Update name, location or reorder threshold |
| `DELETE` | `/items/{id}` | Delete an item and its movements |
| `POST` | `/items/{id}/movements` | Record a stock movement |
| `GET` | `/items/{id}/movements` | Audit log for one item |
| `GET` | `/movements` | Audit log across all items |

Movement reasons: `receipt`, `sale`, `adjustment`, `damage`, `transfer`.

### Error codes

| Code | Status | Meaning |
| --- | --- | --- |
| `VALIDATION_ERROR` | 422 | Malformed request body or query parameters |
| `ITEM_NOT_FOUND` | 404 | No item with that id |
| `DUPLICATE_SKU` | 409 | An item with that SKU already exists |
| `INSUFFICIENT_STOCK` | 409 | The movement would take quantity below zero |

## Docker

```bash
docker build -t quartermaster .
docker run --rm -p 8000:8000 -e SEED_ON_START=true quartermaster
```

The image is a multi-stage build that carries only the resulting virtualenv into
the runtime layer, runs as a non-root user, and declares a healthcheck. The
entrypoint applies migrations before serving, so a container started against an
empty database is immediately usable.

CI builds this image on every push and then *runs* it — waiting for `/health`,
confirming the entrypoint applied migrations, checking the seeded data is
served, and asserting the oversell rule still returns 409 from inside the
container. Building is not the same as working, so the pipeline checks both.

## Project layout

```
app/
  main.py           application factory, error handlers
  config.py         environment-driven settings
  db.py             engine, session factory, declarative base
  models.py         ORM models and database constraints
  schemas.py        API request/response contract
  types.py          UTC-normalising timestamp column
  errors.py         domain errors and their status codes
  routers/          HTTP layer
  services/         business rules and transactions
  repositories/     data access
alembic/            migrations
scripts/seed.py     idempotent sample data
tests/              unit and integration tests
demo.sh             scripted end-to-end CLI demo
```

## License

[MIT](LICENSE)
