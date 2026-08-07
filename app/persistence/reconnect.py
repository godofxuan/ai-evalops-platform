from math import pow

from sqlalchemy.exc import DisconnectionError, InterfaceError, OperationalError

from app.core.random_source import RandomSource, SystemRandomSource


class BoundedReconnectBackoff:
    def __init__(
        self,
        *,
        base_delay_seconds: float = 0.5,
        max_delay_seconds: float = 30.0,
        jitter_ratio: float = 0.2,
        random_source: RandomSource | None = None,
    ) -> None:
        if base_delay_seconds <= 0:
            raise ValueError("base reconnect delay must be positive")
        if max_delay_seconds < base_delay_seconds:
            raise ValueError("maximum reconnect delay must be at least the base delay")
        if not 0 <= jitter_ratio <= 1:
            raise ValueError("reconnect jitter ratio must be between zero and one")
        self._base_delay_seconds = base_delay_seconds
        self._max_delay_seconds = max_delay_seconds
        self._jitter_ratio = jitter_ratio
        self._random_source = random_source or SystemRandomSource()

    def delay_seconds(self, attempt: int) -> float:
        if attempt <= 0:
            raise ValueError("reconnect attempt must be positive")
        exponential = min(
            self._max_delay_seconds,
            self._base_delay_seconds * pow(2.0, min(attempt - 1, 30)),
        )
        sample = self._random_source.random()
        if not 0 <= sample < 1:
            raise ValueError("random source returned a value outside [0, 1)")
        multiplier = 1 + self._jitter_ratio * ((2 * sample) - 1)
        return min(self._max_delay_seconds, max(0.001, exponential * multiplier))


def is_database_connectivity_error(error: BaseException) -> bool:
    return isinstance(
        error,
        (ConnectionError, DisconnectionError, InterfaceError, OperationalError),
    )
