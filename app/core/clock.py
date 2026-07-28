from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Injectable time source used by lease, retry, and recovery policies."""

    def now(self) -> datetime:
        """Return the current timezone-aware UTC instant."""


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
