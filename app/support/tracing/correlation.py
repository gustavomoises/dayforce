"""ASGI middleware: read or create the correlation_id and return it in the response header."""

import re
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.support.tracing.context import correlation_scope

CORRELATION_HEADER = "X-Correlation-ID"
_VALID_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


def new_correlation_id() -> str:
    """A fresh correlation_id (UUID4), also used by the CLI."""
    return str(uuid.uuid4())


def resolve_correlation_id(header_value: str | None) -> str:
    """Reuse a well-formed header value; otherwise generate a new id."""
    if header_value and _VALID_ID.fullmatch(header_value):
        return header_value
    return new_correlation_id()


class CorrelationMiddleware:
    """Sets the correlation_id contextvar per request and echoes it in `X-Correlation-ID`."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = resolve_correlation_id(Headers(scope=scope).get(CORRELATION_HEADER))

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[CORRELATION_HEADER] = correlation_id
            await send(message)

        with correlation_scope(correlation_id):
            await self.app(scope, receive, send_with_header)
