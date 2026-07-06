"""FastAPI application factory for the tooling API.

All routes are namespaced under `/api/tooling/*` (R4: never collide with
tracker routes). Errors are RFC 7807 `application/problem+json` — domain
`ApiError`s, request-validation failures, and bare HTTP errors all render to
the same problem shape.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.tooling.api.config import API_VERSION
from apps.tooling.api.errors import ApiError, api_error_handler, problem_response
from apps.tooling.api.routers import (
    assignments,
    audit,
    auth,
    health,
    machines,
    tool_types,
    tools,
)

API_PREFIX = "/api/tooling"


def create_app() -> FastAPI:
    app = FastAPI(title="Lance Tooling API", version=API_VERSION,
                  docs_url=f"{API_PREFIX}/docs", openapi_url=f"{API_PREFIX}/openapi.json")

    # Starlette types handlers against bare Exception; ApiError is a subclass.
    app.add_exception_handler(ApiError, api_error_handler)  # type: ignore[arg-type]

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_r: Request, exc: RequestValidationError):
        return problem_response(422, "Unprocessable Entity", _render_errors(exc.errors()))

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(_r: Request, exc: StarletteHTTPException):
        title = {401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
                 405: "Method Not Allowed"}.get(exc.status_code, "Error")
        return problem_response(exc.status_code, title, str(exc.detail))

    for module in (health, auth, tools, tool_types, assignments, machines, audit):
        app.include_router(module.router, prefix=API_PREFIX)

    return app


def _render_errors(errors: Sequence[Any]) -> str:
    parts = []
    for e in errors:
        loc = ".".join(str(p) for p in e.get("loc", []) if p != "body")
        parts.append(f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")))
    return "; ".join(parts) or "request validation failed"


app = create_app()
