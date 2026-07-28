import asyncio

from app.core.event_loop import (
    create_psycopg_compatible_event_loop,
    run_with_psycopg_compatible_event_loop,
)


def test_psycopg_compatible_factory_returns_selector_loop() -> None:
    loop = create_psycopg_compatible_event_loop()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()


def test_psycopg_compatible_runner_executes_coroutine() -> None:
    async def return_value() -> str:
        assert isinstance(asyncio.get_running_loop(), asyncio.SelectorEventLoop)
        return "completed"

    assert run_with_psycopg_compatible_event_loop(return_value()) == "completed"


async def test_pytest_async_tests_use_psycopg_compatible_loop() -> None:
    assert isinstance(asyncio.get_running_loop(), asyncio.SelectorEventLoop)
