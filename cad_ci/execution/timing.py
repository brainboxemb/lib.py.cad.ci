"""UTC wall-clock formatting for CAD-CI evidence."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> str:
    """Return current UTC time in ISO-8601 milliseconds with literal Z."""

    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
