"""Keep client IP addresses out of third-party log records.

Application logs must not contain client IPs (Step 9 metrics decision;
platform HTTP logs are documented separately). Our own log calls never pass
addresses; libraries can: slowapi logs the limiter key on 429s and uvicorn
logs WebSocket handshakes as ``<ip>:<port> - "WebSocket <path>" <status>``
on ``uvicorn.error`` even with ``--no-access-log``. This filter renders such
records and replaces any address token (IPv4/IPv6, optionally with a port or
in brackets) with ``[redacted]``.
"""

import logging
from ipaddress import ip_address

REDACTED = "[redacted]"
_STRIP = "()[]{},;'\"<>"


def _is_address(token: str) -> bool:
    candidate = token.strip(_STRIP)
    for value in (candidate, candidate.rsplit(":", 1)[0].strip("[]")):
        try:
            ip_address(value)
        except ValueError:
            continue
        return True
    return False


def redact_addresses(text: str) -> str:
    """Replace whitespace-separated tokens that are IP addresses (with or without a port)."""
    return " ".join(REDACTED if _is_address(token) else token for token in text.split(" "))


class AddressRedactingFilter(logging.Filter):
    """Render the record and redact address tokens from the message."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_addresses(record.getMessage())
        record.args = None
        return True


def install(*logger_names: str) -> None:
    for name in logger_names:
        logger = logging.getLogger(name)
        if not any(isinstance(f, AddressRedactingFilter) for f in logger.filters):
            logger.addFilter(AddressRedactingFilter())
