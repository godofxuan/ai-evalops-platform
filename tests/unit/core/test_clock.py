from datetime import UTC

from app.core.clock import SystemClock


def test_system_clock_returns_utc_aware_time() -> None:
    now = SystemClock().now()

    assert now.tzinfo is UTC
    assert now.utcoffset() is not None
