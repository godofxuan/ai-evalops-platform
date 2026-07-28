import asyncio
from collections.abc import Callable

import pytest

from app.core.event_loop import create_psycopg_compatible_event_loop


def pytest_asyncio_loop_factories(
    config: pytest.Config,
    item: pytest.Item,
) -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
    del config, item
    return {"psycopg-compatible": create_psycopg_compatible_event_loop}
