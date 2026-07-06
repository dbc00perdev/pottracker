"""RFC 7807 `application/problem+json` error handling.

Every error response is a problem document: `{type, title, status, detail}`.
Domain code raises `ApiError` (or a subclass); FastAPI's own validation and
HTTP errors are adapted by the registered handlers in `main.py`.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

PROBLEM_CONTENT_TYPE = "application/problem+json"


class ApiError(Exception):
    """Domain error rendered as an RFC7807 problem document."""

    def __init__(
        self,
        status: int,
        title: str,
        detail: str,
        *,
        type_: str = "about:blank",
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.title = title
        self.detail = detail
        self.type = type_
        self.extra = extra or {}

    def to_response(self) -> JSONResponse:
        body: dict[str, Any] = {
            "type": self.type,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            **self.extra,
        }
        return JSONResponse(status_code=self.status, content=body,
                            media_type=PROBLEM_CONTENT_TYPE)


class NotFound(ApiError):
    def __init__(self, detail: str) -> None:
        super().__init__(404, "Not Found", detail)


class Conflict(ApiError):
    def __init__(self, detail: str, **extra: Any) -> None:
        super().__init__(409, "Conflict", detail, extra=extra or None)


class Unprocessable(ApiError):
    """Business-rule rejection (422) — distinct from request-shape 422s."""

    def __init__(self, detail: str, **extra: Any) -> None:
        super().__init__(422, "Unprocessable Entity", detail, extra=extra or None)


class Unauthorized(ApiError):
    def __init__(self, detail: str = "authentication required") -> None:
        super().__init__(401, "Unauthorized", detail)


class Forbidden(ApiError):
    def __init__(self, detail: str = "insufficient role") -> None:
        super().__init__(403, "Forbidden", detail)


async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return exc.to_response()


def problem_response(status: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"type": "about:blank", "title": title, "status": status, "detail": detail},
        media_type=PROBLEM_CONTENT_TYPE,
    )
