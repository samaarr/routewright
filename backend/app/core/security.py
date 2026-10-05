"""Body/admission limits and response protection for every HTTP path."""

import asyncio
import json
import logging
import time
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

log = logging.getLogger("routewright.security")


class SecurityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.active = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        started = time.monotonic()
        response_started = False

        async def protected_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-request-id", request_id.encode()),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
                        (b"cache-control", b"no-store"),
                    ]
                )
                if settings.hsts_enabled and settings.app_env == "production":
                    headers.append((b"strict-transport-security", b"max-age=31536000"))
                message = {**message, "headers": headers}
            await send(message)

        async def reject(status: int, error: str) -> None:
            await protected_send(
                {
                    "type": "http.response.start",
                    "status": status,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await protected_send(
                {"type": "http.response.body", "body": json.dumps({"error": error}).encode()}
            )

        if self.active >= settings.max_concurrent_requests:
            await reject(503, "capacity_exceeded")
            return
        self.active += 1
        try:
            body = bytearray()
            if scope["method"] in {"POST", "PUT", "PATCH"}:
                headers = dict(scope.get("headers", []))
                try:
                    length = int(headers.get(b"content-length", b"0"))
                    if length < 0:
                        raise ValueError
                except ValueError:
                    await reject(400, "invalid_content_length")
                    return
                if length > settings.max_request_bytes:
                    await reject(413, "request_too_large")
                    return
                if headers.get(b"content-encoding", b"identity") != b"identity":
                    await reject(415, "unsupported_content_encoding")
                    return
                while True:
                    try:
                        message = await asyncio.wait_for(
                            receive(), timeout=max(0.001, 10 - (time.monotonic() - started))
                        )
                    except TimeoutError:
                        await reject(408, "request_timeout")
                        return
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > settings.max_request_bytes:
                        await reject(413, "request_too_large")
                        return
                    if not message.get("more_body", False):
                        break
                if not headers.get(b"content-type", b"").lower().startswith(b"application/json"):
                    await reject(415, "json_required")
                    return
            delivered = False

            async def replay() -> Message:
                nonlocal delivered
                if not delivered and scope["method"] in {"POST", "PUT", "PATCH"}:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self.app(scope, replay, protected_send)
        except Exception as exc:
            # Only type/ID are logged; exception text may contain a provider key or payload.
            log.error(
                "request_failed request_id=%s exception_type=%s", request_id, type(exc).__name__
            )
            if response_started:
                raise
            await reject(503, "service_unavailable")
        finally:
            self.active -= 1
            log.info(
                "request_finished request_id=%s elapsed_ms=%d",
                request_id,
                (time.monotonic() - started) * 1000,
            )
