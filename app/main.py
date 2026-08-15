"""Application factory and error handling."""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import __version__
from app.errors import DomainError
from app.routers import items, movements

DESCRIPTION = """
Inventory and stock-movement API.

* **Items** — SKU, name, quantity, location, reorder threshold.
* **Movements** — an append-only audit log of every quantity change.

Quantity is never set directly. It changes only through a recorded movement, and
a movement that would take stock below zero is rejected.
"""


def _serialisable_errors(errors: list[dict]) -> list[dict]:
    """Reduce Pydantic's error records to JSON-safe fields.

    Pydantic attaches the original exception object under `ctx`, which cannot be
    serialised, and echoes the offending `input` back. Only the location, the
    message, and the error type are useful to a client, so only those are kept.
    """
    return [
        {
            "loc": [str(part) for part in error.get("loc", ())],
            "msg": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in errors
    ]


def _error_response(
    status_code: int, code: str, message: str, details: dict | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message, "details": details or {}}
        },
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="Quartermaster",
        description=DESCRIPTION,
        version=__version__,
        license_info={"name": "MIT", "identifier": "MIT"},
    )

    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Reshaped into the same envelope as domain errors so clients have one
        # error format to parse, not two.
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            "The request body or query parameters are invalid.",
            {"errors": _serialisable_errors(exc.errors())},
        )

    @app.get("/health", tags=["ops"], summary="Liveness probe")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(items.router)
    app.include_router(movements.router)

    return app


app = create_app()
