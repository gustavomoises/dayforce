"""One place that turns errors into {error, detail, correlation_id} responses."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import AppError
from app.support.tracing.context import correlation_scope, get_correlation_id
from app.support.tracing.correlation import CORRELATION_HEADER

logger = logging.getLogger(__name__)


def _body(error: str, detail: object) -> dict[str, object]:
    return {"error": error, "detail": detail, "correlation_id": get_correlation_id()}


async def _app_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    logger.warning("request failed", extra={"error": exc.code, "detail": exc.detail})
    return JSONResponse(_body(exc.code, exc.detail), status_code=exc.status_code)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors() if isinstance(e, dict)]
    return JSONResponse(_body("invalid_input", errors), status_code=422)


async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    """Runs outside CorrelationMiddleware, so the id comes from the request state."""
    correlation_id = getattr(request.state, "correlation_id", None)
    with correlation_scope(correlation_id):
        logger.exception("unexpected error", extra={"error": type(exc).__name__})
        body = _body("internal_error", "unexpected error; see logs")
    headers = {CORRELATION_HEADER: correlation_id} if correlation_id else None
    return JSONResponse(body, status_code=500, headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unexpected)
