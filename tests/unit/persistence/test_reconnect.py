import pytest

from app.persistence.reconnect import BoundedReconnectBackoff


class FixedRandom:
    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value


def test_reconnect_backoff_is_exponential_and_bounded() -> None:
    backoff = BoundedReconnectBackoff(
        base_delay_seconds=0.5,
        max_delay_seconds=2.0,
        jitter_ratio=0,
        random_source=FixedRandom(0.5),
    )

    assert [backoff.delay_seconds(attempt) for attempt in range(1, 6)] == [
        0.5,
        1.0,
        2.0,
        2.0,
        2.0,
    ]


@pytest.mark.parametrize("sample", [0.0, 0.999999])
def test_reconnect_jitter_never_exceeds_the_configured_bound(sample: float) -> None:
    backoff = BoundedReconnectBackoff(
        base_delay_seconds=1.0,
        max_delay_seconds=4.0,
        jitter_ratio=0.5,
        random_source=FixedRandom(sample),
    )

    delay = backoff.delay_seconds(20)

    assert 0 < delay <= 4.0


@pytest.mark.parametrize("attempt", [0, -1])
def test_reconnect_backoff_rejects_invalid_attempt(attempt: int) -> None:
    backoff = BoundedReconnectBackoff()

    with pytest.raises(ValueError):
        backoff.delay_seconds(attempt)
