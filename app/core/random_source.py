import random
from typing import Protocol


class RandomSource(Protocol):
    def random(self) -> float:
        """Return a deterministic-in-tests value in [0, 1)."""


class SystemRandomSource:
    def __init__(self) -> None:
        self._random = random.SystemRandom()

    def random(self) -> float:
        return self._random.random()
