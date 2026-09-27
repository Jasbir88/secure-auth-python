"""
Security middleware for the application.
"""
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import time
import uuid


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        if "/auth/" in request.url.path:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"

        return response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add unique request ID to each request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Emit structured request completion logs."""

    async def dispatch(self, request: Request, call_next) -> Response:
        logger = logging.getLogger("secure_auth.request")
        start_time = time.monotonic()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round(
                (time.monotonic() - start_time) * 1000,
                2,
            )

            logger.exception(
                "request_failed",
                extra={
                    "event": "http_request",
                    "request_id": getattr(
                        request.state,
                        "request_id",
                        None,
                    ),
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": duration_ms,
                },
            )
            raise

        duration_ms = round(
            (time.monotonic() - start_time) * 1000,
            2,
        )

        response.headers["X-Process-Time"] = str(duration_ms)

        logger.info(
            "request_completed",
            extra={
                "event": "http_request",
                "request_id": getattr(
                    request.state,
                    "request_id",
                    None,
                ),
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )

        return response
