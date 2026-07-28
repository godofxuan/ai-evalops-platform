from dataclasses import dataclass
from datetime import timedelta


class InvalidLeaseConfiguration(ValueError):
    """Lease duration is not safe for worker coordination."""


@dataclass(frozen=True, slots=True)
class LeasePolicy:
    duration: timedelta

    def __post_init__(self) -> None:
        if self.duration <= timedelta(0):
            raise InvalidLeaseConfiguration("lease duration must be positive")
        if self.duration > timedelta(hours=1):
            raise InvalidLeaseConfiguration("lease duration must not exceed one hour")
