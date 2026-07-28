import asyncio
from collections.abc import Coroutine
from typing import Any


def create_psycopg_compatible_event_loop() -> asyncio.AbstractEventLoop:
    """Return the selector loop required by Psycopg async on Windows."""
    return asyncio.SelectorEventLoop()


def run_with_psycopg_compatible_event_loop[T](
    coroutine: Coroutine[Any, Any, T],
) -> T:
    return asyncio.run(
        coroutine,
        loop_factory=create_psycopg_compatible_event_loop,
    )
